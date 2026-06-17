"""白字识别器 — 封装 WhiteTextMatcher，内置 appear/disappear 确认计数器。"""

from pathlib import Path

import numpy as np

from loco_box.image_ops import load_bgr
from loco_box.matcher import WhiteTextMatcher, MatchAnalysis
from loco_box.recognition.base import BaseRecognizer
from loco_box.types import RecognitionResult


class WhiteTextRecognizer(BaseRecognizer):
    """基于笔画指纹的白字检测。

    JSON params:
        brightness: int = 200       - 白色像素阈值
        threshold: float = 0.45     - 匹配分数阈值
        mode: str = "appear"        - "appear" 或 "disappear"
        confirm_count: int = 4      - 连续命中多少次才确认
        template: str               - 模板 PNG 路径（相对于 data/templates/）
    """

    def __init__(self, params: dict):
        self._brightness = int(params.get("brightness", 200))
        self._threshold = float(params.get("threshold", 0.45))
        self._mode = params.get("mode", "appear")
        self._confirm_count = int(params.get("confirm_count", 4))
        self._matcher: WhiteTextMatcher | None = None
        self._hits = 0

        template_path = params.get("template", "")
        if template_path:
            # 支持绝对路径和相对路径
            p = Path(template_path)
            if not p.is_absolute():
                # 相对于项目根目录
                p = Path(__file__).resolve().parent.parent.parent / "data" / "templates" / template_path
            bgr = load_bgr(str(p))
            if bgr is not None:
                self._matcher = WhiteTextMatcher(bgr, self._brightness)

    def recognize(self, image: np.ndarray, params: dict) -> RecognitionResult:
        if self._matcher is None:
            return RecognitionResult(success=False, score=0, matched=False,
                                     metadata={"error": "no template"})

        result: MatchAnalysis = self._matcher.analyze(image, self._threshold)

        if self._mode == "appear":
            self._hits = self._hits + 1 if result.strong_present else 0
        else:  # disappear
            self._hits = self._hits + 1 if (result.absent or not result.weak_present) else 0

        matched = self._hits >= self._confirm_count
        return RecognitionResult(
            success=True,
            score=result.score,
            matched=matched,
            metadata={
                "hits": self._hits,
                "confirm_count": self._confirm_count,
                "strong": result.strong_present,
                "weak": result.weak_present,
                "absent": result.absent,
            },
        )

    def reset(self) -> None:
        self._hits = 0
