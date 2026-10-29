"""配置持久化：按功能命名空间 + 旧配置自动迁移。"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


DATA_DIR = _app_root() / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"
TEMPLATE_FILE = DATA_DIR / "template.png"
SCORES_DIR = DATA_DIR / "scores"

_OLD_FIELDS = ("delay", "threshold", "brightness", "trigger_delay", "template_region", "region_b")


class ConfigStore:
    """JSON 配置：{com_port, features:{<feature_id>: {<params>}}}。

    首次加载时若检测到旧的扁平结构（顶层 delay/template_region 等），
    自动迁移到 box_monitor 命名空间并落盘，参数不丢。
    """

    def __init__(self) -> None:
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not SETTINGS_FILE.exists():
            return {"com_port": "AUTO", "features": {}}
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {"com_port": "AUTO", "features": {}}
        if not isinstance(data, dict):
            return {"com_port": "AUTO", "features": {}}

        if "features" not in data and any(k in data for k in _OLD_FIELDS):
            data = self._migrate(data)
            self._write(data)

        data.setdefault("com_port", "AUTO")
        data.setdefault("features", {})
        return data

    @staticmethod
    def _migrate(data: Dict[str, Any]) -> Dict[str, Any]:
        box: Dict[str, Any] = {}
        for k in _OLD_FIELDS:
            if k in data:
                box[k] = data[k]
        new: Dict[str, Any] = {"com_port": data.get("com_port", "AUTO"), "features": {}}
        if box:
            new["features"]["box_monitor"] = box
        return new

    def _write(self, data: Optional[Dict[str, Any]] = None) -> None:
        if data is None:
            data = self._data
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    # ── 功能配置 ──────────────────────────────────
    def get(self, feature_id: str) -> Dict[str, Any]:
        return self._data.get("features", {}).get(feature_id, {})

    def set(self, feature_id: str, config: Dict[str, Any]) -> None:
        self._data.setdefault("features", {})[feature_id] = config
        self._write()

    # ── 全局配置 ──────────────────────────────────
    def get_global(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set_global(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._write()
