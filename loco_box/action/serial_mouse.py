"""Arduino 鼠标点击动作。"""
from typing import Optional

from loco_box.action.base import BaseAction
from loco_box.controller import Controller
from loco_box.types import ActionResult


class SerialMouseAction(BaseAction):
    """通过 Arduino 发送鼠标点击。

    JSON params:
        button: str = "left"  - "left" 或 "right"
    """

    def execute(self, controller: Controller, params: dict, context: Optional[dict] = None) -> ActionResult:
        button = params.get("button", "left")
        ok = controller.mouse_click(button)
        return ActionResult(success=ok, message=f"mouse {button}" if ok else f"mouse {button} FAILED")
