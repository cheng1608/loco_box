"""后端运行时单例：Arduino 控制器 + 事件总线 + 配置 + 功能注册表。"""

from backend.core.arduino import ArduinoController
from backend.core.config import ConfigStore
from backend.core.events import EventBus
from backend.features import FeatureContext, create_features

arduino = ArduinoController()
bus = EventBus()
config = ConfigStore()

# 注入配置，供 ArduinoController 在 AUTO 解析时用 com_port 兜底
arduino.set_config(config)

ctx = FeatureContext(arduino, bus, config)
features = create_features(ctx)
