"""用户配置持久化。"""

import json
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from loco_box.capture import Region

SETTINGS_DIR = Path.home() / ".loco_box"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
TEMPLATE_FILE = SETTINGS_DIR / "template.png"


def _valid_region(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    required = ("left", "top", "width", "height")
    return all(k in value for k in required) and all(
        isinstance(value[k], (int, float)) and value[k] >= 0 for k in required
    )


def _normalize_region(value: dict) -> Region:
    return {
        "left": int(value["left"]),
        "top": int(value["top"]),
        "width": int(value["width"]),
        "height": int(value["height"]),
    }


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(
    template_region: Optional[Region],
    region_b: Optional[Region],
    delay: str,
    threshold: str,
    brightness: str,
) -> None:
    data: dict[str, Any] = {
        "delay": delay,
        "threshold": threshold,
        "brightness": brightness,
    }
    if template_region:
        data["template_region"] = template_region
    if region_b:
        data["region_b"] = region_b

    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def parse_saved_regions(data: dict) -> tuple[Optional[Region], Optional[Region]]:
    template_region = None
    region_b = None
    if _valid_region(data.get("template_region")):
        template_region = _normalize_region(data["template_region"])
    if _valid_region(data.get("region_b")):
        region_b = _normalize_region(data["region_b"])
    return template_region, region_b


def save_template_image(bgr: np.ndarray) -> None:
    """保存框选监控区域时的截图，用作匹配模板。"""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(TEMPLATE_FILE), bgr)


def load_template_image() -> Optional[np.ndarray]:
    """读取上次保存的监控区域截图。"""
    if not TEMPLATE_FILE.exists():
        return None
    img = cv2.imread(str(TEMPLATE_FILE))
    if img is None or img.size == 0:
        return None
    return img
