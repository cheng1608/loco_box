"""丢球：循环 鼠标左键长按 → Shift，无识别步骤。

复用原 App._throw_loop 的按键序列，Arduino 走共享底座。
四个时间间隔（鼠标按住 / 鼠标后间隔 / Shift 按住 / Shift 后间隔）可配置。
"""

import threading
from typing import Any, Dict, Optional

from backend.features import Feature, FeatureContext, register
from loco_box.serial_bridge import SerialBridge


@register
class ThrowFeature(Feature):
    id = "throw"
    name = "丢球"
    config_schema = [
        {"key": "mouse_hold", "label": "左键按住(ms)", "type": "number", "default": 200},
        {"key": "mouse_gap", "label": "左键后间隔(ms)", "type": "number", "default": 150},
        {"key": "shift_hold", "label": "Shift按住(ms)", "type": "number", "default": 50},
        {"key": "shift_gap", "label": "Shift后间隔(ms)", "type": "number", "default": 50},
    ]

    def __init__(self, ctx: FeatureContext) -> None:
        super().__init__(ctx)
        self._active = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._times: Dict[str, int] = {}

    def is_running(self) -> bool:
        return self._active

    def start(self, config: Dict[str, Any]) -> None:
        # 若已在运行，先停旧循环再按新参数重启
        old = self._thread
        if old and old.is_alive():
            self._active = False
            self._stop_event.set()
            old.join(timeout=1.0)
            if old.is_alive():
                raise ValueError("丢球正在停止，请稍后重试")

        self._times = {
            "mouse_hold": self._time_ms(config, "mouse_hold", 200),
            "mouse_gap": self._time_ms(config, "mouse_gap", 150),
            "shift_hold": self._time_ms(config, "shift_hold", 50),
            "shift_gap": self._time_ms(config, "shift_gap", 50),
        }
        self._active = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    @staticmethod
    def _time_ms(config: Dict[str, Any], key: str, default: int) -> int:
        try:
            return max(0, int(float(config.get(key, default))))
        except (TypeError, ValueError):
            return default

    def stop(self) -> None:
        self._active = False
        self._stop_event.set()
        self.ctx.bus.publish_status("扔球已停止")

    def _loop(self) -> None:
        if not self.ctx.arduino.is_connected():
            com = SerialBridge.find_arduino() or self.ctx.config.get_global("com_port", "AUTO")
            if not self.ctx.arduino.connect(com):
                self.ctx.bus.publish_status("Arduino 连接失败")
                self._active = False
                return
            self.ctx.bus.publish_status(f"Arduino 已就绪 · {com}")

        if self._stop_event.is_set():
            return
        self.ctx.bus.publish_status("扔球中")
        try:
            while not self._stop_event.is_set():
                if not self.ctx.arduino.is_connected():
                    self.ctx.bus.publish_status("Arduino 断连，丢球已停止")
                    return
                # Firmware owns the hold; wait for hold + gap, but allow stop
                # to interrupt the wait before another key can be sent.
                if not self.ctx.arduino.send("MOUSE_LEFT", self._times["mouse_hold"]):
                    return
                if self._stop_event.wait((self._times["mouse_hold"] + self._times["mouse_gap"]) / 1000.0):
                    return
                if not self.ctx.arduino.send("LSHIFT", self._times["shift_hold"]):
                    return
                if self._stop_event.wait((self._times["shift_hold"] + self._times["shift_gap"]) / 1000.0):
                    return
        finally:
            self._active = False
