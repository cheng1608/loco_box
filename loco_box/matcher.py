"""白色文字笔画指纹匹配。"""

from dataclasses import dataclass

import numpy as np

from loco_box.image_ops import bgr_to_gray, edge_density, gaussian_blur_gray, lap_var


@dataclass
class MatchAnalysis:
    absent: bool
    strong_present: bool
    weak_present: bool
    score: float
    detail: str


def _screen_metrics(gray: np.ndarray, brightness: int) -> dict:
    return {
        "mean": float(gray.mean()),
        "std": float(gray.std()),
        "bright_ratio": float(np.count_nonzero(gray >= brightness)) / gray.size,
        "edge_density": edge_density(gray),
        "lap_var": lap_var(gray),
    }


def _is_white_field(metrics: dict, brightness: int) -> bool:
    if metrics["bright_ratio"] > 0.88 and metrics["std"] < 22:
        return True
    if metrics["bright_ratio"] > 0.82 and metrics["edge_density"] < 0.012 and metrics["lap_var"] < 100:
        return True
    return metrics["mean"] >= brightness - 8 and metrics["std"] < 14


def _peak_blobs(mask: np.ndarray, min_pixels: int = 20) -> list[dict]:
    col_sum = mask.sum(axis=0).astype(np.float64) / 255.0
    if col_sum.max() < 1:
        return []

    threshold = max(2.0, col_sum.max() * 0.15)
    blobs: list[dict] = []
    in_peak, start = False, 0

    def add_blob(x0: int, x1: int):
        ys, xs = np.where(mask[:, x0:x1] > 0)
        if len(xs) >= min_pixels:
            blobs.append({"cx": float(x0 + (x1 - x0) / 2), "cy": float(ys.mean()), "area": float(len(xs))})

    for x, value in enumerate(col_sum):
        if value >= threshold and not in_peak:
            start, in_peak = x, True
        elif value < threshold and in_peak:
            add_blob(start, x)
            in_peak = False
    if in_peak:
        add_blob(start, len(col_sum))
    return blobs


def _analyze_mask(mask: np.ndarray) -> dict:
    total = mask.size
    stroke_pixels = int(np.count_nonzero(mask))
    blobs = _peak_blobs(mask)
    largest = max((int(b["area"]) for b in blobs), default=0)
    return {
        "stroke_pixels": stroke_pixels,
        "stroke_ratio": stroke_pixels / total if total else 0.0,
        "char_count": len(blobs),
        "largest_blob_ratio": largest / total if total else 0.0,
        "blobs": blobs,
    }


def _layout_similarity(tpl_blobs: list[dict], frame_blobs: list[dict], height: int) -> float:
    if len(tpl_blobs) < 3 or len(frame_blobs) < 3:
        return 0.0
    tpl_xs = [b["cx"] for b in tpl_blobs]
    frame_xs = [b["cx"] for b in frame_blobs]
    tpl_gaps = np.diff(tpl_xs)
    frame_gaps = np.diff(frame_xs)
    if len(tpl_gaps) == 0 or len(frame_gaps) == 0:
        return 0.0
    tpl_mean, frame_mean = float(tpl_gaps.mean()), float(frame_gaps.mean())
    if tpl_mean < 2:
        return 0.0
    gap_ratio = min(frame_mean / tpl_mean, tpl_mean / frame_mean)
    y_diff = abs(float(np.mean([b["cy"] for b in tpl_blobs])) - float(np.mean([b["cy"] for b in frame_blobs])))
    y_score = max(0.0, 1.0 - y_diff / max(height * 0.25, 1))
    return 0.55 * gap_ratio + 0.45 * y_score


def _band_coverage(tpl_stroke: np.ndarray, frame_stroke: np.ndarray, n_bands: int = 5) -> tuple[float, float]:
    w = tpl_stroke.shape[1]
    coverages = []
    for i in range(n_bands):
        x1, x2 = i * w // n_bands, (i + 1) * w // n_bands
        tpl_band, frame_band = tpl_stroke[:, x1:x2], frame_stroke[:, x1:x2]
        tpl_pixels = int(np.count_nonzero(tpl_band))
        if tpl_pixels < 8:
            continue
        inter = int(np.count_nonzero((tpl_band > 0) & (frame_band > 0)))
        coverages.append(inter / tpl_pixels)
    if len(coverages) < 3:
        return 0.0, 0.0
    return float(min(coverages)), float(np.mean(coverages))


def _empty_result(gray: np.ndarray, metrics: dict) -> tuple[np.ndarray, dict]:
    empty = np.zeros_like(gray)
    return empty, {
        **metrics,
        "stroke_pixels": 0,
        "stroke_ratio": 0.0,
        "char_count": 0,
        "largest_blob_ratio": 0.0,
        "blobs": [],
    }


def extract_text_strokes(bgr: np.ndarray, brightness: int = 200) -> tuple[np.ndarray, dict]:
    gray = bgr_to_gray(bgr)
    metrics = _screen_metrics(gray, brightness)
    if _is_white_field(metrics, brightness):
        return _empty_result(gray, metrics)

    blurred = gaussian_blur_gray(gray, radius=2)
    tophat = np.clip(gray.astype(np.int16) - blurred.astype(np.int16), 0, 255).astype(np.uint8)
    strokes = ((tophat > 25) & (gray >= brightness)).astype(np.uint8) * 255
    meta = {**metrics, **_analyze_mask(strokes)}

    if meta["stroke_ratio"] > 0.75 or meta["largest_blob_ratio"] > 0.60:
        return _empty_result(gray, meta)
    return strokes, meta


class WhiteTextMatcher:
    def __init__(self, template_bgr: np.ndarray, brightness: int = 200):
        self.brightness = brightness
        self.tpl_stroke, meta = extract_text_strokes(template_bgr, brightness)
        self.tpl_meta = meta
        self.tpl_stroke_pixels = meta["stroke_pixels"]
        self.tpl_char_count = meta["char_count"]
        self.tpl_blobs = meta["blobs"]
        self._tpl_h = template_bgr.shape[0]

    @property
    def tpl_mask(self) -> np.ndarray:
        return self.tpl_stroke

    @property
    def is_valid(self) -> bool:
        return (
            self.tpl_stroke_pixels >= 40
            and self.tpl_char_count >= 3
            and 0.03 <= self.tpl_meta["stroke_ratio"] <= 0.65
        )

    def analyze(self, frame_bgr: np.ndarray, threshold: float) -> MatchAnalysis:
        gray = bgr_to_gray(frame_bgr)
        metrics = _screen_metrics(gray, self.brightness)
        if _is_white_field(metrics, self.brightness):
            return MatchAnalysis(True, False, False, 0.0, f"白屏 亮={metrics['bright_ratio']:.0%}")

        frame_stroke, frame_meta = extract_text_strokes(frame_bgr, self.brightness)
        if frame_meta["stroke_pixels"] == 0:
            return MatchAnalysis(True, False, False, 0.0, "无笔画")

        inter = int(np.count_nonzero((frame_stroke > 0) & (self.tpl_stroke > 0)))
        union = int(np.count_nonzero((frame_stroke > 0) | (self.tpl_stroke > 0)))
        coverage = inter / self.tpl_stroke_pixels
        iou = inter / union if union else 0.0
        min_band, mean_band = _band_coverage(self.tpl_stroke, frame_stroke)
        layout = _layout_similarity(self.tpl_blobs, frame_meta["blobs"], self._tpl_h)

        tc, fc = self.tpl_char_count, frame_meta["char_count"]
        char_sim = 1.0 - min(1.0, abs(fc - tc) / max(tc, 1))
        score = 0.35 * coverage + 0.20 * iou + 0.20 * mean_band + 0.15 * layout + 0.10 * char_sim
        detail = f"重合={coverage:.2f} 带={min_band:.2f}/{mean_band:.2f} 布局={layout:.2f} 块={fc}/{tc} 分={score:.2f}"

        if coverage < 0.12 or min_band < 0.10 or layout < 0.20:
            return MatchAnalysis(True, False, False, score, detail)

        strong = (
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
        weak = strong or (coverage >= 0.30 and min_band >= 0.22 and layout >= 0.35 and score >= threshold - 0.05)
        return MatchAnalysis(False, strong, weak, score, detail)
