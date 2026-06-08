"""截图与图像处理（Pillow + numpy）。"""

from pathlib import Path
from typing import Optional, Union

import mss
import numpy as np
from PIL import Image, ImageFilter

from loco_box.types import Region


def grab_region(region: Region) -> np.ndarray:
    with mss.mss() as sct:
        return bgra_to_bgr(np.array(sct.grab(region)))


def bgra_to_bgr(bgra: np.ndarray) -> np.ndarray:
    return bgra[:, :, :3].copy()


def bgr_to_gray(bgr: np.ndarray) -> np.ndarray:
    return np.dot(bgr[..., :3], [0.114, 0.587, 0.299]).astype(np.uint8)


def gray_to_bgr(gray: np.ndarray) -> np.ndarray:
    return np.stack([gray, gray, gray], axis=-1)


def bgr_to_rgb(bgr: np.ndarray) -> np.ndarray:
    return bgr[..., ::-1].copy()


def rgb_to_bgr(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., ::-1].copy()


def save_bgr(path: Union[Path, str], bgr: np.ndarray) -> None:
    Image.fromarray(bgr_to_rgb(bgr)).save(path)


def load_bgr(path: Union[Path, str]) -> Optional[np.ndarray]:
    try:
        with Image.open(path) as img:
            return rgb_to_bgr(np.array(img.convert("RGB")))
    except OSError:
        return None


def render_bgr_preview(bgr: np.ndarray, width: int, height: int, bg_hex: str) -> Image.Image:
    pil_img = Image.fromarray(bgr_to_rgb(bgr))
    scale = min(width / pil_img.width, height / pil_img.height)
    new_size = (max(1, int(pil_img.width * scale)), max(1, int(pil_img.height * scale)))
    if scale < 1.0:
        pil_img = pil_img.resize(new_size, Image.Resampling.LANCZOS)
    bg_rgb = tuple(int(bg_hex.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    canvas = Image.new("RGB", (width, height), bg_rgb)
    canvas.paste(pil_img, ((width - pil_img.width) // 2, (height - pil_img.height) // 2))
    return canvas


def gaussian_blur_gray(gray: np.ndarray, radius: int = 2) -> np.ndarray:
    return np.array(Image.fromarray(gray).filter(ImageFilter.GaussianBlur(radius=radius)))


def edge_density(gray: np.ndarray) -> float:
    gx = np.abs(np.diff(gray.astype(np.int16), axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray.astype(np.int16), axis=0, prepend=gray[:1, :]))
    return float(((gx + gy) > 40).mean())


def lap_var(gray: np.ndarray) -> float:
    g = gray.astype(np.float64)
    lap = -4 * g + np.roll(g, 1, 0) + np.roll(g, -1, 0) + np.roll(g, 1, 1) + np.roll(g, -1, 1)
    return float(lap.var())
