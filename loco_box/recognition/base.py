"""识别器基类。"""

from abc import ABC, abstractmethod

import numpy as np

from loco_box.types import RecognitionResult


class BaseRecognizer(ABC):
    """所有识别器必须实现此接口。"""

    @abstractmethod
    def recognize(self, image: np.ndarray, params: dict) -> RecognitionResult:
        """对单帧图像运行识别，返回结果。params 来自 JSON 任务定义。"""
        ...

    def reset(self) -> None:
        """重置内部状态（如确认计数器）。默认无操作。"""
        pass
