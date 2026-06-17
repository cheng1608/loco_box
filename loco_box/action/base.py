"""动作基类。"""

from abc import ABC, abstractmethod
from typing import Optional

from loco_box.controller import Controller
from loco_box.types import ActionResult


class BaseAction(ABC):
    """所有动作必须实现此接口。"""

    @abstractmethod
    def execute(self, controller: Controller, params: dict, context: Optional[dict] = None) -> ActionResult:
        """执行动作。context 携带上下文数据（如识别结果）。"""
        ...
