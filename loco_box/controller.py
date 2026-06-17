"""硬件抽象控制器。统一截图和输入，解耦识别器/动作与底层实现。"""

import time
from typing import Optional

import numpy as np

from loco_box.image_ops import grab_region
from loco_box.serial_bridge import SerialBridge
from loco_box.types import Region


class Controller:
    """MAA 式的 Controller：截图 + 输入。"""

    def __init__(self, com_port: str = "AUTO", baudrate: int = 9600):
        self._com_port = com_port
        self._bridge = SerialBridge(com_port, baudrate)

    @property
    def port(self) -> str:
        return self._bridge.port if self._bridge.port != "AUTO" else self._com_port

    def connect(self) -> bool:
        """连接 Arduino，失败不抛异常。支持自动检测和重试。"""
        return self._bridge.connect()

    def disconnect(self) -> None:
        self._bridge.disconnect()

    def is_connected(self) -> bool:
        return self._bridge.is_connected()

    # ─── 截图 ──────────────────────────────────────
    def screenshot(self, region: Region) -> np.ndarray:
        """截取指定区域，返回 BGR numpy 数组。"""
        return grab_region(region)

    # ─── 输入 ──────────────────────────────────────
    def press_key(self, key: str, hold_ms: int = 0) -> bool:
        """按下键盘按键。key: "1", "ESC", "LCTRL" 等。"""
        return self._bridge.send(key, hold_ms)

    def mouse_click(self, button: str = "left") -> bool:
        """鼠标点击。button: "left" 或 "right"。"""
        cmd = "MOUSE_LEFT" if button == "left" else "MOUSE_RIGHT"
        return self._bridge.send(cmd)

    def hold_key(self, key: str, ms: int) -> bool:
        """按住按键指定毫秒后松开。"""
        return self._bridge.send(key, ms)

    # ─── 静态工具 ──────────────────────────────────
    @staticmethod
    def find_arduino() -> Optional[str]:
        return SerialBridge.find_arduino()

    @staticmethod
    def list_ports() -> list[str]:
        return SerialBridge.list_ports()
