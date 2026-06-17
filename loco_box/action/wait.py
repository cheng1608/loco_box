"""延时等待动作。"""
from typing import Optional

import time

from loco_box.action.base import BaseAction
from loco_box.controller import Controller
from loco_box.types import ActionResult


class WaitAction(BaseAction):
    """等待指定时间。

    JSON params:
        duration_ms: int   - 等待毫秒数
        duration_s: float  - 等待秒数（与 duration_ms 二选一）
    """

    def execute(self, controller: Controller, params: dict, context: Optional[dict] = None) -> ActionResult:
        if "duration_ms" in params:
            ms = int(params["duration_ms"])
        elif "duration_s" in params:
            ms = int(float(params["duration_s"]) * 1000)
        else:
            ms = 1000
        time.sleep(ms / 1000.0)
        return ActionResult(success=True, message=f"waited {ms}ms")
