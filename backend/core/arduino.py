"""Arduino 串口控制（单例封装 SerialBridge）。

封装串口只连一次并保持的策略：ATmega32U4 打开串口会触发硬件复位，
USB HID 需约 3s 重新枚举，因此 connect 后保持连接、不复位。
"""

import threading
from typing import Optional

from loco_box.serial_bridge import SerialBridge


class ArduinoController:
    def __init__(self) -> None:
        self._bridge: Optional[SerialBridge] = None
        self._lock = threading.Lock()
        self._config = None  # ConfigStore 注入，用于 com_port 兜底

    def set_config(self, config) -> None:
        """注入 ConfigStore（在 state 初始化后调用），避免循环 import。"""
        self._config = config

    def is_connected(self) -> bool:
        b = self._bridge
        return b is not None and b.is_connected()

    def port(self) -> Optional[str]:
        b = self._bridge
        return b.port if b else None

    def _resolve_port(self, com_port: str) -> Optional[str]:
        """把 AUTO 解析成真实 COM 口：find_arduino 优先，配置兜底。"""
        if com_port and com_port.upper() != "AUTO":
            return com_port
        detected = SerialBridge.find_arduino()
        if detected:
            return detected
        if self._config is not None:
            saved = self._config.get_global("com_port", "AUTO")
            if saved and str(saved).upper() != "AUTO":
                return str(saved)
        return None

    def connect(self, com_port: str) -> bool:
        """连接并等待复位完成（阻塞约 3s）。请在后台/worker 线程调用。"""
        with self._lock:
            if self._bridge and self._bridge.is_connected():
                return True
            port = self._resolve_port(com_port)
            if not port:
                return False
            bridge = SerialBridge(port)
            if not bridge.connect_and_wait():
                return False
            self._bridge = bridge
            # 记住本次成功端口，供下次兜底
            if self._config is not None:
                self._config.set_global("com_port", port)
            return True

    def disconnect(self) -> None:
        with self._lock:
            if self._bridge:
                self._bridge.disconnect()
                self._bridge = None

    def send(self, key: str, hold_ms: int = 0) -> bool:
        b = self._bridge
        if b is None or not b.is_connected():
            return False
        return b.send(key, hold_ms)

    def press_key(self, key: str, hold_ms: int = 50) -> bool:
        return self.send(key, hold_ms)

    def mouse_left(self) -> bool:
        return self.send("MOUSE_LEFT")

    def mouse_right(self) -> bool:
        return self.send("MOUSE_RIGHT")
