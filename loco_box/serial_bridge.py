"""通过串口与 Arduino 开发板通信，模拟键盘按键和鼠标点击。

协议 (文本，每行一条命令):
    键盘: "1"-"9", "0", "a"-"z", "ESC", "TAB", "SPACE", "ENTER"
          "LCTRL", "RCTRL", "LSHIFT", "RSHIFT"
          "LEFT", "RIGHT", "UP", "DOWN"
          "F1"-"F12"
    鼠标: "MOUSE_LEFT", "MOUSE_RIGHT"

用法:
    from loco_box.serial_bridge import SerialBridge
    bridge = SerialBridge()
    bridge.connect()
    bridge.send("1", 50)       # 按数字 1，按住 50ms
    bridge.send("MOUSE_LEFT")  # 鼠标左键点击
"""

import time
from typing import Optional

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None


class SerialBridge:
    def __init__(self, port: str = "AUTO", baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate
        self._ser: Optional[serial.Serial] = None

    def connect(self) -> bool:
        """打开串口连接，返回是否成功。"""
        if serial is None:
            return False
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=1)
            return True
        except (OSError, serial.SerialException):
            return False

    def disconnect(self):
        """关闭串口连接。"""
        if self._ser and self._ser.is_open:
            self._ser.close()

    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def connect_and_wait(self, reset_wait: float = 3.0) -> bool:
        """打开串口并等待 ATmega32U4 复位 + USB HID 重新枚举完成。

        ATmega32U4 打开串口会触发硬件复位，USB HID 约需 reset_wait 秒
        才能重新枚举，此期间发送的按键无效。本方法连接成功后同步阻塞
        reset_wait 秒，请在后台线程调用以免卡住 GUI。
        """
        if self.is_connected():
            return True
        if not self.connect():
            return False
        time.sleep(reset_wait)
        return True

    def send(self, key: str, hold_ms: int = 0) -> bool:
        """发送按键命令。
        key: 按键名 ("1", "ESC", "MOUSE_LEFT" 等)
        hold_ms: 按住毫秒数，0 为瞬时点击，>0 为长按
        """
        try:
            if self._ser and self._ser.is_open:
                cmd = f"{key}:{hold_ms}" if hold_ms > 0 else key
                self._ser.write((cmd + "\n").encode())
                self._ser.flush()
                return True
        except (OSError, serial.SerialException):
            self.disconnect()
        return False

    def press_key(self, key: str, hold_ms: int = 50) -> bool:
        """按下按键。hold_ms 默认 50ms，确保游戏能响应。"""
        return self.send(key, hold_ms)

    def mouse_left(self) -> bool:
        return self.send("MOUSE_LEFT")

    def mouse_right(self) -> bool:
        return self.send("MOUSE_RIGHT")

    # ─── 静态工具 ────────────────────────────────────
    @staticmethod
    def list_ports() -> list[str]:
        if serial is None:
            return []
        return [f"{p.device} - {p.description}" for p in serial.tools.list_ports.comports()]

    @staticmethod
    def find_arduino() -> Optional[str]:
        """自动查找 Arduino 所在的串口。"""
        if serial is None:
            return None
        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").lower()
            if "arduino" in desc or "micro" in desc:
                return p.device
        return None
