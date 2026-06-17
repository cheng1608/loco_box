"""动作注册表。"""

from loco_box.action.base import BaseAction


class ActionRegistry:
    def __init__(self):
        self._registry: dict[str, type[BaseAction]] = {}
        self._register_defaults()

    def register(self, name: str, cls: type[BaseAction]) -> None:
        self._registry[name] = cls

    def create(self, name: str) -> BaseAction:
        cls = self._registry.get(name)
        if cls is None:
            raise KeyError(f"Unknown action: {name}. Available: {list(self._registry.keys())}")
        return cls()

    def list_types(self) -> list[str]:
        return list(self._registry.keys())

    def _register_defaults(self) -> None:
        from loco_box.action.serial_key import SerialKeyAction
        from loco_box.action.serial_mouse import SerialMouseAction
        from loco_box.action.wait import WaitAction
        from loco_box.action.log import LogAction
        from loco_box.action.screenshot import ScreenshotAction
        from loco_box.action.sequence import SequenceAction

        self.register("serial_key", SerialKeyAction)
        self.register("serial_mouse", SerialMouseAction)
        self.register("wait", WaitAction)
        self.register("log", LogAction)
        self.register("screenshot", ScreenshotAction)
        self.register("sequence", SequenceAction)
