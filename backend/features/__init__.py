"""功能插件框架：Feature 基类 + 注册表。

各功能是松散自动化脚本，唯一强共享 Arduino 控制底座（通过 ctx.arduino）。
截图/识别/框选是按需注入的可选能力。新增功能只需：
    1. 继承 Feature，实现 start/stop/is_running
    2. 用 @register 装饰器注册
    3. 在 create_features 里 import 该模块（触发注册）
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Type


class FeatureContext:
    """注入给 Feature 的运行时依赖。"""

    def __init__(self, arduino: Any, bus: Any, config: Any) -> None:
        self.arduino = arduino      # ArduinoController
        self.bus = bus              # EventBus
        self.config = config        # ConfigStore


class Feature(ABC):
    id: str = ""
    name: str = ""
    # 参数声明（供前端渲染表单 / 文档）：[{key, label, type, default, ...}]
    config_schema: List[Dict[str, Any]] = []

    def __init__(self, ctx: FeatureContext) -> None:
        self.ctx = ctx

    @abstractmethod
    def start(self, config: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def is_running(self) -> bool:
        ...

    def default_config(self) -> Dict[str, Any]:
        return {s["key"]: s.get("default") for s in self.config_schema}


_REGISTRY: Dict[str, Type[Feature]] = {}


def register(cls: Type[Feature]) -> Type[Feature]:
    _REGISTRY[cls.id] = cls
    return cls


def create_features(ctx: FeatureContext) -> Dict[str, Feature]:
    from backend.features import box_monitor, music, throw  # noqa: F401 触发注册

    return {fid: cls(ctx) for fid, cls in _REGISTRY.items()}
