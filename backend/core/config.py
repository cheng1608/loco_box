"""配置持久化：按功能命名空间 + 旧配置自动迁移。"""

import json
import os
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional


# The desktop runs this repository's Python backend; there is no frozen
# PyInstaller runtime. Anchor data to the source, independent of the cwd.
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
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
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not SETTINGS_FILE.exists():
            return {"com_port": "AUTO", "features": {}}
        try:
            with open(SETTINGS_FILE, encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            return {"com_port": "AUTO", "features": {}}
        if not isinstance(data, dict):
            return {"com_port": "AUTO", "features": {}}

        data.setdefault("com_port", "AUTO")
        if not isinstance(data.get("features"), dict):
            data["features"] = {}
        legacy = {key: data.pop(key) for key in _OLD_FIELDS if key in data}
        if legacy:
            # Clean up mixed old/new files too. Current settings take priority;
            # unrelated global fields and other features must survive migration.
            current = data["features"].get("box_monitor", {})
            if isinstance(current, dict):
                legacy.update(current)
            data["features"]["box_monitor"] = legacy
            self._write(data)
        return data

    def _write(self, data: Optional[Dict[str, Any]] = None) -> None:
        if data is None:
            data = self._data
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # A failed write must not truncate the user's only settings file.
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=str(DATA_DIR),
                prefix="settings-", suffix=".tmp", delete=False,
            ) as fh:
                temp_path = fh.name
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_path, SETTINGS_FILE)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    # ── 功能配置 ──────────────────────────────────
    def get(self, feature_id: str) -> Dict[str, Any]:
        with self._lock:
            value = self._data.get("features", {}).get(feature_id, {})
            return deepcopy(value) if isinstance(value, dict) else {}

    def set(self, feature_id: str, config: Dict[str, Any]) -> None:
        with self._lock:
            data = deepcopy(self._data)
            data.setdefault("features", {})[feature_id] = deepcopy(config)
            self._write(data)
            self._data = data

    def update(self, feature_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Merge one feature's fields without losing concurrent player settings."""
        with self._lock:
            merged = self.get(feature_id)
            merged.update(deepcopy(patch))
            self.set(feature_id, merged)
            return deepcopy(merged)

    # ── 全局配置 ──────────────────────────────────
    def get_global(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return deepcopy(self._data.get(key, default))

    def set_global(self, key: str, value: Any) -> None:
        with self._lock:
            data = deepcopy(self._data)
            data[key] = deepcopy(value)
            self._write(data)
            self._data = data
