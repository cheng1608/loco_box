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
    bridge.send("1")           # 按数字 1
    bridge.send("ESC")         # 按 ESC
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
            time.sleep(0.15)  # Arduino 复位等待
            return True
        except (OSError, serial.SerialException):
            return False

    def disconnect(self):
        """关闭串口连接。"""
        if self._ser and self._ser.is_open:
            self._ser.close()

    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def send(self, key: str, hold_ms: int = 0) -> bool:
        """发送按键命令。
        key: 按键名 ("1", "ESC", "MOUSE_LEFT" 等)
        hold_ms: 按住毫秒数，0 为点击，>0 为长按
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

    # 快捷方式
    def press_key(self, key: str) -> bool:
        """点击按键（向下兼容）"""
        return self.send(key)

    def hold_key(self, key: str, ms: int) -> bool:
        """按住按键指定毫秒数"""
        return self.send(key, ms)

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
