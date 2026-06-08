"""用户配置持久化。"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from loco_box.image_ops import load_bgr, save_bgr
from loco_box.types import Region


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


SETTINGS_DIR = _app_root() / "data"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
TEMPLATE_FILE = SETTINGS_DIR / "template.png"


@dataclass
class AppConfig:
    delay: str = "1"
    threshold: str = "0.45"
    brightness: str = "200"
    template_region: Optional[Region] = None
    region_b: Optional[Region] = None


def _valid_region(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    keys = ("left", "top", "width", "height")
    return all(k in value and isinstance(value[k], (int, float)) and value[k] >= 0 for k in keys)


def _normalize_region(value: dict) -> Region:
    return {k: int(value[k]) for k in ("left", "top", "width", "height")}


def load_config() -> AppConfig:
    if not SETTINGS_FILE.exists():
        return AppConfig()
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return AppConfig()
    if not isinstance(data, dict):
        return AppConfig()

    cfg = AppConfig(
        delay=str(data.get("delay", "1")),
        threshold=str(data.get("threshold", "0.45")),
        brightness=str(data.get("brightness", "200")),
    )
    if _valid_region(data.get("template_region")):
        cfg.template_region = _normalize_region(data["template_region"])
    if _valid_region(data.get("region_b")):
        cfg.region_b = _normalize_region(data["region_b"])
    return cfg


def save_config(cfg: AppConfig, template_bgr: Optional[np.ndarray] = None) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "delay": cfg.delay,
        "threshold": cfg.threshold,
        "brightness": cfg.brightness,
    }
    if cfg.template_region:
        data["template_region"] = cfg.template_region
    if cfg.region_b:
        data["region_b"] = cfg.region_b
    with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    if template_bgr is not None:
        save_bgr(TEMPLATE_FILE, template_bgr)


def load_template_image() -> Optional[np.ndarray]:
    if not TEMPLATE_FILE.exists():
        return None
    return load_bgr(TEMPLATE_FILE)
