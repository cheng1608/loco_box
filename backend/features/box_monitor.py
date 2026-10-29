"""惊喜盒子监控：白字识别 → 延时按键 → 截图。

复用 loco_box.matcher.WhiteTextMatcher + loco_box.monitor.MonitorThread，
回调改为通过 ctx.bus 推送给前端（后端无 GUI 主循环）。
"""

import threading
from typing import Any, Dict, Optional, TYPE_CHECKING

from backend.core.config import TEMPLATE_FILE
from backend.features import Feature, FeatureContext, register
from loco_box.serial_bridge import SerialBridge
from loco_box.types import Region

if TYPE_CHECKING:
    import numpy as np
    from loco_box.monitor import MonitorThread


@register
class BoxMonitorFeature(Feature):
    id = "box_monitor"
    name = "惊喜盒子"
    config_schema = [
        {"key": "delay", "label": "截图延时(s)", "type": "number", "default": "1"},
        {"key": "threshold", "label": "匹配阈值", "type": "number", "default": "0.45"},
        {"key": "brightness", "label": "亮度阈值", "type": "number", "default": "200"},
        {"key": "trigger_delay", "label": "触发延时(s)", "type": "number", "default": "5.0"},
    ]

    def __init__(self, ctx: FeatureContext) -> None:
        super().__init__(ctx)
        self._monitor: Optional[MonitorThread] = None
        self._timer: Optional[threading.Timer] = None
        self._box_count = 0
        self._config: Dict[str, Any] = {}

    def is_running(self) -> bool:
        return self._monitor is not None and self._monitor.is_running()

    def start(self, config: Dict[str, Any]) -> None:
        from loco_box.image_ops import load_bgr
        from loco_box.matcher import WhiteTextMatcher
        from loco_box.monitor import MonitorThread

        template_region: Optional[Region] = config.get("template_region")
        region_b: Optional[Region] = config.get("region_b")
        if not template_region:
            raise ValueError("请先框选监控区域")
        if not region_b:
            raise ValueError("请先框选截图区域")

        template_bgr = load_bgr(TEMPLATE_FILE)
        if template_bgr is None:
            raise ValueError("请先在盒子出现时框选监控区域以保存模板")

        brightness = int(float(config.get("brightness", 200)))
        matcher = WhiteTextMatcher(template_bgr, brightness)
        if not matcher.is_valid:
            raise ValueError("模板笔画结构不足，请在盒子出现时重新框选监控区域")

        try:
            delay = float(config.get("delay", 1))
            threshold = float(config.get("threshold", 0.45))
        except (TypeError, ValueError):
            raise ValueError("延迟和阈值必须是有效数字")
        if delay < 0:
            raise ValueError("延迟不能为负数")

        if self._monitor:
            self._monitor.stop()

        self._config = config
        self._box_count = 0
        self.ctx.bus.publish_count(0)

        # 后台连接 Arduino（约 3s 复位），监控先行启动
        com = SerialBridge.find_arduino() or self.ctx.config.get_global("com_port", "AUTO")
        threading.Thread(target=self._connect_arduino, args=(com,), daemon=True).start()

        self._monitor = MonitorThread(
            monitor_region=template_region,
            shot_region=region_b,
            matcher=matcher,
            delay_sec=delay,
            threshold=threshold,
            on_screenshot=self._on_screenshot,
            on_status=lambda msg: self.ctx.bus.publish_status(msg),
            on_error=self._on_error,
            on_box_appear=self._on_box_appear,
        )
        self._monitor.start()
        self.ctx.bus.publish_status("监控中")

    def stop(self) -> None:
        if self._monitor:
            self._monitor.stop()
            self._monitor = None
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.ctx.bus.publish_status("已停止")

    # ── 模板持久化 ─────────────────────────────────
    def capture_template(self) -> Dict[str, Any]:
        """框选监控区后抓取当前区域作为白字模板，持久化到 data/template.png。"""
        from loco_box.image_ops import grab_region, save_bgr
        from loco_box.matcher import WhiteTextMatcher

        cfg = self.ctx.config.get("box_monitor")
        region: Optional[Region] = cfg.get("template_region")
        if not region:
            raise ValueError("请先框选监控区域")
        bgr = grab_region(region)
        save_bgr(TEMPLATE_FILE, bgr)
        brightness = int(float(cfg.get("brightness", 200)))
        matcher = WhiteTextMatcher(bgr, brightness)
        return {"ok": True, "valid": matcher.is_valid, "stroke_pixels": matcher.tpl_stroke_pixels}

    # ── Arduino ────────────────────────────────────
    def _connect_arduino(self, com: str) -> None:
        if self.ctx.arduino.connect(com):
            self.ctx.bus.publish_status(f"Arduino 已就绪 · {self.ctx.arduino.port()}")
        else:
            self.ctx.bus.publish_status("Arduino 连接失败")

    # ── 回调 ──────────────────────────────────────
    def _on_screenshot(self, image_bgr: "np.ndarray") -> None:
        from backend.core.screen import encode_jpeg_b64

        # 计数已在「盒子出现」时 +1，这里只推截图，并带上当前计数
        self.ctx.bus.publish_shot(encode_jpeg_b64(image_bgr), self._box_count)

    def _on_box_appear(self) -> None:
        self._box_count += 1
        self.ctx.bus.publish_count(self._box_count)
        try:
            delay_ms = int(float(self._config.get("trigger_delay", 5.0)) * 1000)
        except (TypeError, ValueError):
            delay_ms = 5000
        if delay_ms < 0:
            delay_ms = 0
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(delay_ms / 1000.0, self._send_key)
        self._timer.start()
        self.ctx.bus.publish_status(f"按键已预约 · {delay_ms / 1000:.1f}s")

    def _send_key(self) -> None:
        self._timer = None
        if not self.ctx.arduino.is_connected():
            self.ctx.bus.publish_status("Arduino 断连")
            return
        self.ctx.arduino.press_key("1", hold_ms=50)
        self.ctx.bus.publish_status("按键已发送")

    def _on_error(self, msg: str) -> None:
        self.ctx.bus.publish_status(f"监控错误: {msg}")
        self.stop()
