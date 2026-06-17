"""任务上下文数据结构。"""

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from loco_box.types import RecognitionResult


@dataclass
class TaskContext:
    """在流水线执行期间传递的上下文。"""
    regions: dict = field(default_factory=dict)
    screenshot: Optional[np.ndarray] = None
    recognition_result: Optional[RecognitionResult] = None
    variables: dict[str, Any] = field(default_factory=dict)
    iteration: int = 0
    poll_count: int = 0
