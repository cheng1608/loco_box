"""日志输出动作。"""
from typing import Optional

from loco_box.action.base import BaseAction
from loco_box.controller import Controller
from loco_box.types import ActionResult


class LogAction(BaseAction):
    """输出一条日志。

    JSON params:
        message: str - 日志内容
    """

    def execute(self, controller: Controller, params: dict, context: Optional[dict] = None) -> ActionResult:
        msg = params.get("message", "")
        print(f"[Pipeline] {msg}")
        return ActionResult(success=True, message=msg)
