"""截图与 JPEG 编码（复用 image_ops.grab_region，BGR 约定不变）。"""

import base64
from io import BytesIO
from typing import Optional, Tuple

import numpy as np
from PIL import Image

from loco_box.image_ops import bgr_to_rgb, grab_region
from loco_box.types import Region


def grab_bgr(region: Region) -> np.ndarray:
    return grab_region(region)


def encode_jpeg_b64(
    bgr: np.ndarray, quality: int = 70, max_size: Optional[Tuple[int, int]] = None,
) -> str:
    img = Image.fromarray(bgr_to_rgb(bgr))
    if max_size is not None:
        img.thumbnail(max_size, Image.Resampling.BILINEAR)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def grab_jpeg_b64(
    region: Region, quality: int = 70, max_size: Optional[Tuple[int, int]] = None,
) -> str:
    """截图并编码为 base64 JPEG（同步，供后台线程调用）。"""
    return encode_jpeg_b64(grab_region(region), quality, max_size)


def primary_monitor_region() -> Optional[Region]:
    import mss

    try:
        with mss.mss() as sct:
            mon = sct.monitors[1]
        return {
            "left": mon["left"],
            "top": mon["top"],
            "width": mon["width"],
            "height": mon["height"],
        }
    except Exception:
        return None
