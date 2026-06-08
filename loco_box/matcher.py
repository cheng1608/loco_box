"""白色文字笔画指纹匹配。"""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class MatchAnalysis:
    absent: bool
    strong_present: bool
    weak_present: bool
    score: float
    detail: str


def _screen_metrics(bgr: np.ndarray, brightness: int) -> dict:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 160)
    return {
        "mean": float(gray.mean()),
        "std": float(gray.std()),
        "bright_ratio": float(np.count_nonzero(gray >= brightness)) / gray.size,
        "edge_density": float(np.count_nonzero(edges)) / edges.size,
        "lap_var": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
    }


def is_white_field(metrics: dict, brightness: int) -> bool:
    if metrics["bright_ratio"] > 0.88 and metrics["std"] < 22:
        return True
    if metrics["bright_ratio"] > 0.82 and metrics["edge_density"] < 0.012 and metrics["lap_var"] < 100:
        return True
    if metrics["mean"] >= brightness - 8 and metrics["std"] < 14:
        return True
    return False


def _get_blobs(mask: np.ndarray, min_area: int = 20) -> list[dict]:
    h, w = mask.shape
    total = h * w
    blobs = []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        bx, by, bw, bh = cv2.boundingRect(contour)
        if bw * bh > total * 0.5:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            continue
        blobs.append({
            "cx": moments["m10"] / moments["m00"],
            "cy": moments["m01"] / moments["m00"],
            "area": float(area),
        })
    blobs.sort(key=lambda b: b["cx"])
    return blobs


def _stroke_structure(mask: np.ndarray) -> dict:
    h, w = mask.shape
    total = h * w
    stroke_pixels = int(np.count_nonzero(mask))
    stroke_ratio = stroke_pixels / total if total else 0.0
    blobs = _get_blobs(mask)
    largest = max((int(b["area"]) for b in blobs), default=0)
    return {
        "stroke_pixels": stroke_pixels,
        "stroke_ratio": stroke_ratio,
        "char_count": len(blobs),
        "largest_blob_ratio": largest / total if total else 0.0,
        "blobs": blobs,
    }


def _layout_similarity(tpl_blobs: list[dict], frame_blobs: list[dict], height: int) -> float:
    if len(tpl_blobs) < 3 or len(frame_blobs) < 3:
        return 0.0
    tpl_xs = [b["cx"] for b in tpl_blobs]
    frame_xs = [b["cx"] for b in frame_blobs]
    tpl_gaps = [tpl_xs[i + 1] - tpl_xs[i] for i in range(len(tpl_xs) - 1)]
    frame_gaps = [frame_xs[i + 1] - frame_xs[i] for i in range(len(frame_xs) - 1)]
    if not tpl_gaps or not frame_gaps:
        return 0.0
    tpl_gap_mean = float(np.mean(tpl_gaps))
    frame_gap_mean = float(np.mean(frame_gaps))
    if tpl_gap_mean < 2:
        return 0.0
    gap_ratio = min(frame_gap_mean / tpl_gap_mean, tpl_gap_mean / frame_gap_mean)
    tpl_y = float(np.mean([b["cy"] for b in tpl_blobs]))
    frame_y = float(np.mean([b["cy"] for b in frame_blobs]))
    y_score = max(0.0, 1.0 - abs(tpl_y - frame_y) / max(height * 0.25, 1))
    return 0.55 * gap_ratio + 0.45 * y_score


def _band_coverage(tpl_stroke: np.ndarray, frame_stroke: np.ndarray, n_bands: int = 5) -> tuple[float, float]:
    h, w = tpl_stroke.shape
    coverages = []
    for i in range(n_bands):
        x1, x2 = i * w // n_bands, (i + 1) * w // n_bands
        tpl_band = tpl_stroke[:, x1:x2]
        frame_band = frame_stroke[:, x1:x2]
        tpl_pixels = int(np.count_nonzero(tpl_band))
        if tpl_pixels < 8:
            continue
        inter = int(np.count_nonzero(cv2.bitwise_and(tpl_band, frame_band)))
        coverages.append(inter / tpl_pixels)
    if len(coverages) < 3:
        return 0.0, 0.0
    return float(min(coverages)), float(np.mean(coverages))


def extract_text_strokes(bgr: np.ndarray, brightness: int = 200) -> tuple[np.ndarray, dict]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    metrics = _screen_metrics(bgr, brightness)

    if is_white_field(metrics, brightness):
        empty = np.zeros_like(gray)
        return empty, {**metrics, "stroke_pixels": 0, "stroke_ratio": 0.0, "char_count": 0, "largest_blob_ratio": 0.0}

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
    _, strokes = cv2.threshold(tophat, 25, 255, cv2.THRESH_BINARY)
    bright = (gray >= brightness).astype(np.uint8) * 255
    strokes = cv2.bitwise_and(strokes, bright)
    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    strokes = cv2.morphologyEx(strokes, cv2.MORPH_CLOSE, close_k)

    struct = _stroke_structure(strokes)
    meta = {**metrics, **struct}

    if struct["stroke_ratio"] > 0.75 or struct["largest_blob_ratio"] > 0.60:
        empty = np.zeros_like(gray)
        return empty, {**meta, "stroke_pixels": 0, "stroke_ratio": 0.0, "char_count": 0, "largest_blob_ratio": 0.0}

    return strokes, meta


class WhiteTextMatcher:
    """五字横向笔画指纹匹配。"""

    def __init__(self, template_bgr: np.ndarray, brightness: int = 200):
        self.brightness = brightness
        self.template_bgr = template_bgr
        self.tpl_stroke, self.tpl_meta = extract_text_strokes(template_bgr, brightness)
        self.tpl_mask = self.tpl_stroke
        self.tpl_stroke_pixels = self.tpl_meta["stroke_pixels"]
        self.tpl_char_count = self.tpl_meta["char_count"]
        self.tpl_blobs = self.tpl_meta["blobs"]
        self.white_pixel_count = self.tpl_stroke_pixels
        self._tpl_h = template_bgr.shape[0]

    @property
    def is_valid(self) -> bool:
        return (
            self.tpl_stroke_pixels >= 40
            and self.tpl_char_count >= 3
            and 0.03 <= self.tpl_meta["stroke_ratio"] <= 0.65
        )

    def _overlap_scores(self, frame_stroke: np.ndarray) -> tuple[float, float]:
        inter = int(np.count_nonzero(cv2.bitwise_and(frame_stroke, self.tpl_stroke)))
        union = int(np.count_nonzero(cv2.bitwise_or(frame_stroke, self.tpl_stroke)))
        coverage = inter / self.tpl_stroke_pixels if self.tpl_stroke_pixels else 0.0
        iou = inter / union if union else 0.0
        return coverage, iou

    def analyze(self, frame_bgr: np.ndarray, threshold: float) -> MatchAnalysis:
        metrics = _screen_metrics(frame_bgr, self.brightness)
        if is_white_field(metrics, self.brightness):
            return MatchAnalysis(True, False, False, 0.0, f"白屏 亮={metrics['bright_ratio']:.0%}")

        frame_stroke, frame_meta = extract_text_strokes(frame_bgr, self.brightness)
        if frame_meta["stroke_pixels"] == 0:
            return MatchAnalysis(True, False, False, 0.0, "无笔画")

        coverage, iou = self._overlap_scores(frame_stroke)
        min_band, mean_band = _band_coverage(self.tpl_stroke, frame_stroke)
        layout = _layout_similarity(self.tpl_blobs, frame_meta["blobs"], self._tpl_h)

        tc = self.tpl_char_count
        fc = frame_meta["char_count"]
        char_sim = 1.0 - min(1.0, abs(fc - tc) / max(tc, 1)) if tc > 0 else 0.0
        score = 0.35 * coverage + 0.20 * iou + 0.20 * mean_band + 0.15 * layout + 0.10 * char_sim

        detail = (
            f"重合={coverage:.2f} 带={min_band:.2f}/{mean_band:.2f} "
            f"布局={layout:.2f} 块={fc}/{tc} 分={score:.2f}"
        )

        clearly_absent = coverage < 0.12 or min_band < 0.10 or layout < 0.20
        if clearly_absent:
            return MatchAnalysis(True, False, False, score, detail)

        strong_present = (
            score >= threshold + 0.08
            and coverage >= max(0.45, threshold + 0.05)
            and iou >= 0.30
            and min_band >= 0.32
            and mean_band >= 0.38
            and layout >= 0.48
            and abs(fc - tc) <= 3
            and frame_meta["stroke_ratio"] <= 0.65
            and frame_meta["largest_blob_ratio"] <= 0.45
            and metrics["edge_density"] >= 0.014
        )

        weak_present = strong_present or (
            coverage >= 0.30
            and min_band >= 0.22
            and layout >= 0.35
            and score >= threshold - 0.05
        )

        return MatchAnalysis(False, strong_present, weak_present, score, detail)
