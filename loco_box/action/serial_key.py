"""Arduino 键盘按键动作。"""
from typing import Optional

from loco_box.action.base import BaseAction
from loco_box.controller import Controller
from loco_box.types import ActionResult


class SerialKeyAction(BaseAction):
    """通过 Arduino 发送键盘按键。

    JSON params:
        key: str       - 按键名 ("1", "ESC", "LCTRL" 等)
        hold_ms: int   - 按住毫秒数，0=点击 (默认)
    """

    def execute(self, controller: Controller, params: dict, context: Optional[dict] = None) -> ActionResult:
        key = params.get("key", "1")
        hold_ms = int(params.get("hold_ms", 0))
        ok = controller.press_key(key, hold_ms)
        return ActionResult(success=ok, message=f"key {key}" if ok else f"key {key} FAILED")
