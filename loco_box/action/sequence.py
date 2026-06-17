"""顺序执行多个子动作。"""
from typing import Optional

from loco_box.action.base import BaseAction
from loco_box.action.registry import ActionRegistry
from loco_box.controller import Controller
from loco_box.types import ActionResult


class SequenceAction(BaseAction):
    """依次执行多个子动作。任一失败则停止。

    JSON params:
        actions: list[dict] - 子动作列表，每个为 {"type": "...", "params": {...}}
    """

    def __init__(self):
        self._registry = ActionRegistry()

    def execute(self, controller: Controller, params: dict, context: Optional[dict] = None) -> ActionResult:
        actions = params.get("actions", [])
        for i, action_def in enumerate(actions):
            action_type = action_def.get("type", "")
            action_params = action_def.get("params", {})
            try:
                action = self._registry.create(action_type)
            except KeyError:
                return ActionResult(success=False, message=f"unknown action: {action_type}")

            result = action.execute(controller, action_params, context)
            if not result.success:
                return ActionResult(success=False, message=f"[{i}] {action_type}: {result.message}")
        return ActionResult(success=True, message=f"sequence done ({len(actions)} actions)")
