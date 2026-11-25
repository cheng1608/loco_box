"""丢球：循环 鼠标左键长按 → Shift，无识别步骤。

Arduino 连接、端口选择和按键统一走共享控制器。
四个时间间隔（鼠标按住 / 鼠标后间隔 / Shift 按住 / Shift 后间隔）可配置。
"""

import threading
from typing import Any, Dict, Optional

from backend.core.arduino import DeviceBusyError
from backend.features import Feature, FeatureContext, register


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
        self._control_lock = threading.RLock()

    def is_running(self) -> bool:
        return self._active

    def start(self, config: Dict[str, Any]) -> None:
        with self._control_lock:
            self._start(config)

    def _start(self, config: Dict[str, Any]) -> None:
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
        if not self.ctx.arduino.acquire(self.id):
            raise DeviceBusyError("设备正在被其他功能使用，请先停止该功能")
        self._active = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        try:
            self._thread.start()
        except Exception:
            self._active = False
            self.ctx.arduino.release(self.id)
            raise

    @staticmethod
    def _time_ms(config: Dict[str, Any], key: str, default: int) -> int:
        try:
            return max(0, int(float(config.get(key, default))))
        except (TypeError, ValueError):
            return default

    def stop(self) -> None:
        with self._control_lock:
            self._active = False
            self._stop_event.set()
            worker = self._thread
            if worker and worker is not threading.current_thread():
                worker.join(timeout=1.0)
            self.ctx.bus.publish_status("扔球已停止")

    def _loop(self) -> None:
        try:
            self._run()
        finally:
            self._active = False
            self.ctx.arduino.release(self.id)

    def _run(self) -> None:
        if not self.ctx.arduino.is_connected():
            if not self.ctx.arduino.connect(owner=self.id):
                self.ctx.bus.publish_status("Arduino 连接失败")
                return
            self.ctx.bus.publish_status(f"Arduino 已就绪 · {self.ctx.arduino.port()}")

        if self._stop_event.is_set():
            return
        self.ctx.bus.publish_status("扔球中")
        while not self._stop_event.is_set():
            if not self.ctx.arduino.is_connected():
                self.ctx.bus.publish_status("Arduino 断连，丢球已停止")
                return
            # Firmware owns the hold; wait for hold + gap, but allow stop
            # to interrupt the wait before another key can be sent.
            if not self.ctx.arduino.send("MOUSE_LEFT", self._times["mouse_hold"], owner=self.id):
                return
            if self._stop_event.wait((self._times["mouse_hold"] + self._times["mouse_gap"]) / 1000.0):
                return
            if not self.ctx.arduino.send("LSHIFT", self._times["shift_hold"], owner=self.id):
                return
            if self._stop_event.wait((self._times["shift_hold"] + self._times["shift_gap"]) / 1000.0):
                return
