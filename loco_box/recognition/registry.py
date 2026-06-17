"""识别器注册表。"""

from loco_box.recognition.base import BaseRecognizer


class RecognizerRegistry:
    def __init__(self):
        self._registry: dict[str, type[BaseRecognizer]] = {}
        self._register_defaults()

    def register(self, name: str, cls: type[BaseRecognizer]) -> None:
        self._registry[name] = cls

    def create(self, name: str, params: dict) -> BaseRecognizer:
        cls = self._registry.get(name)
        if cls is None:
            raise KeyError(f"Unknown recognizer: {name}. Available: {list(self._registry.keys())}")
        return cls(params)

    def list_types(self) -> list[str]:
        return list(self._registry.keys())

    def _register_defaults(self) -> None:
        from loco_box.recognition.white_text import WhiteTextRecognizer
        self.register("white_text", WhiteTextRecognizer)
