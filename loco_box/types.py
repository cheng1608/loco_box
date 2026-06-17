"""公共类型。"""

from dataclasses import dataclass, field
from typing import Any, Optional

# mss 区域: left, top, width, height
Region = dict


@dataclass
class RecognitionResult:
    """识别器返回结果。"""
    success: bool = True
    score: float = 0.0
    matched: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    region: Optional[Region] = None


@dataclass
class ActionResult:
    """动作执行结果。"""
    success: bool = True
    message: str = ""


@dataclass
class TaskResult:
    """单个任务的执行结果。"""
    task_name: str = ""
    completed: bool = True
    next_task: Optional[str] = None
    error: Optional[str] = None
