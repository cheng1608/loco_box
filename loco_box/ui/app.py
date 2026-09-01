"""CustomTkinter 主窗口 — 页面管理 + 业务逻辑。"""

from typing import Callable, Optional

import threading
import numpy as np
from tkinter import messagebox

from loco_box.image_ops import grab_region, gray_to_bgr
from loco_box.matcher import WhiteTextMatcher
from loco_box.monitor import MonitorThread
from loco_box.region_selector import select_region
from loco_box.serial_bridge import SerialBridge
from loco_box.settings import AppConfig, load_config, load_template_image, save_config
from loco_box.types import Region
from loco_box.ui.pages import HomePage, SettingsPage
from loco_box.ui.theme import (
    COLORS,
    WINDOW_ALPHA,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)


class App:
    """持有全部状态和业务逻辑。UI 委托给 HomePage / SettingsPage。"""

    def __init__(self, root):
        self.root = root
        self.root.title("")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", WINDOW_ALPHA)
        self.root.configure(fg_color=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 共享状态
        self.template_region: Optional[Region] = None
        self.region_b: Optional[Region] = None
        self.template_bgr: Optional[np.ndarray] = None
        self.matcher: Optional[WhiteTextMatcher] = None
        self.monitor: Optional[MonitorThread] = None
        self._box_count = 0
        self._show_box_count_overlay = False
        self._last_shot_bgr: Optional[np.ndarray] = None
        self._trigger_timer_id: Optional[str] = None
        self._bridge: Optional[SerialBridge] = None
        self._throw_active = False
        self._throw_cooldown = False
        self._throw_thread: Optional[threading.Thread] = None

        self._build_pages()
        self._load_settings()
        self.show_page("home")

        self.root.update_idletasks()
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")

    # ── 页面管理 ──────────────────────────────────

    def _build_pages(self):
        self.home_page = HomePage(self.root, self)
        self.settings_page = SettingsPage(self.root, self)

    def show_page(self, name: str):
        pages = {"home": self.home_page, "settings": self.settings_page}
        for p in pages.values():
            p.pack_forget()
        pages[name].pack(fill="both", expand=True)

    # ── 状态栏（委托给首页）───────────────────────

    def _set_status(self, text: str):
        self.home_page.set_status(text)

    # ── 预览（委托给首页）─────────────────────────

    def _display_image(self, image_bgr: np.ndarray):
        self.home_page.show_preview(image_bgr, self._show_box_count_overlay)

    def _refresh_box_count_display(self):
        if self._last_shot_bgr is not None:
            self._display_image(self._last_shot_bgr)
        else:
            self.home_page.show_placeholder()

    def _set_monitor_button(self, running: bool):
        self.home_page.set_monitor_button(running)

    # ── 监控开关 ──────────────────────────────────

    def _toggle_monitor(self):
        if self.monitor and self.monitor.is_running():
            self._stop()
        else:
            self._start()

    def _ensure_not_monitoring(self) -> bool:
        if self.monitor and self.monitor.is_running():
            messagebox.showwarning("提示", "请先停止监控再操作。")
            return False
        return True

    def _validate_ready(self) -> bool:
        if not self.template_region:
            messagebox.showerror("错误", "请先在设置中选择监控区域。")
            return False
        self._rebuild_matcher()
        if not self.matcher or not self.matcher.is_valid:
            messagebox.showerror("错误", "笔画结构不足，请重新框选或调低亮度。")
            return False
        if not self.region_b:
            messagebox.showerror("错误", "请先在设置中选择截图区域。")
            return False
        return True

    def _start(self):
        if not self._validate_ready():
            return
        try:
            delay = float(self.settings_page.entry_delay.get())
            threshold = float(self.settings_page.entry_threshold.get())
        except ValueError:
            messagebox.showerror("错误", "延迟和阈值必须是有效数字。")
            return
        if delay < 0:
            messagebox.showerror("错误", "延迟不能为负数。")
            return

        if self.monitor:
            self.monitor.stop()

        # 后台连接 Arduino（等 3s 复位+HID 就绪），监控先行启动
        com = SerialBridge.find_arduino() or self.settings_page.entry_com.get().strip()
        if self._bridge:
            self._bridge.disconnect()
        self._bridge = SerialBridge(com)
        self.settings_page.entry_com.delete(0, "end")
        self.settings_page.entry_com.insert(0, com)
        threading.Thread(target=self._init_arduino, daemon=True).start()

        self._box_count = 0
        self._last_shot_bgr = None
        self._show_box_count_overlay = True
        self._refresh_box_count_display()

        self.monitor = MonitorThread(
            monitor_region=self.template_region,
            shot_region=self.region_b,
            matcher=self.matcher,
            delay_sec=delay,
            threshold=threshold,
            on_screenshot=lambda img: self.root.after(0, self._on_monitor_screenshot, img),
            on_status=lambda msg: self.root.after(0, self._set_status, msg),
            on_error=lambda msg: self.root.after(0, self._on_monitor_error, msg),
            on_box_appear=lambda: self.root.after(0, self._on_box_appear),
        )
        self._persist_settings()
        self.monitor.start()
        self._set_monitor_button(True)
        self._set_status("监控中")

    def _stop(self):
        if self.monitor:
            self.monitor.stop()
        if self._trigger_timer_id is not None:
            self.root.after_cancel(self._trigger_timer_id)
            self._trigger_timer_id = None
        if self._throw_active:
            self._throw_active = False
            self.home_page.set_throw_button(False)
        if self._bridge:
            self._bridge.disconnect()
            self._bridge = None
        self._set_monitor_button(False)
        self._set_status("已停止")

    def _on_monitor_error(self, msg: str):
        messagebox.showerror("监控错误", msg)
        self._stop()

    # ── Arduino 初始化 ────────────────────────────

    def _init_arduino(self):
        """后台初始化 Arduino：连接 + 等待复位完成。"""
        import time
        if self._bridge.connect():
            time.sleep(3.0)  # ATmega32U4 复位 + HID 枚举
            self.root.after(0, self._set_status, f"Arduino 已就绪 · {self._bridge.port}")
        else:
            self._bridge = None
            self.root.after(0, self._set_status, "Arduino 连接失败")

    # ── 盒子检测 → 按键触发 ───────────────────────

    def _on_box_appear(self):
        if self._trigger_timer_id is not None:
            self.root.after_cancel(self._trigger_timer_id)
            self._trigger_timer_id = None
        try:
            delay_ms = int(float(self.settings_page.entry_trigger.get()) * 1000)
        except (ValueError, TypeError):
            delay_ms = 5000
        if delay_ms < 0:
            delay_ms = 0
        self._trigger_timer_id = self.root.after(delay_ms, self._do_trigger)
        self._set_status(f"按键已预约 · {delay_ms / 1000:.1f}s")

    def _do_trigger(self):
        self._trigger_timer_id = None
        threading.Thread(target=self._send_key, daemon=True).start()

    def _send_key(self):
        if not self._bridge or not self._bridge.is_connected():
            self.root.after(0, self._set_status, "Arduino 断连")
            return
        self._bridge.press_key("1", hold_ms=50)
        self.root.after(0, self._set_status, "按键已发送")

    # ── 扔球 ──────────────────────────────────────

    def _toggle_throw(self):
        # 按钮冷却中，忽略点击
        if self._throw_cooldown:
            return

        if self._throw_active:
            self._throw_active = False
            self.home_page.set_throw_button(False)
            self._set_status("扔球已停止")
        else:
            self._throw_active = True
            self.home_page.set_throw_button(True)
            self._throw_thread = threading.Thread(target=self._throw_loop, daemon=True)
            self._throw_thread.start()

        # 5s 冷却
        self._throw_cooldown = True
        self.home_page.btn_throw.configure(state="disabled")
        self.root.after(5000, self._reset_throw_cooldown)

    def _reset_throw_cooldown(self):
        self._throw_cooldown = False
        self.home_page.btn_throw.configure(state="normal")

    def _throw_loop(self):
        """循环：按住左键 200ms → 等 150ms → 按 Shift 50ms → 等 50ms，直到 _throw_active 为 False。"""
        import time

        # 确保 Arduino 已连接
        if not self._bridge or not self._bridge.is_connected():
            com = SerialBridge.find_arduino() or self.settings_page.entry_com.get().strip()
            if self._bridge:
                self._bridge.disconnect()
            self._bridge = SerialBridge(com)
            if not self._bridge.connect():
                self._bridge = None
                self._throw_active = False
                self.root.after(0, self.home_page.set_throw_button, False)
                self.root.after(0, self._set_status, "Arduino 连接失败")
                return
            time.sleep(3.0)  # ATmega32U4 复位 + HID 枚举
            self.root.after(0, self._set_status, f"Arduino 已就绪 · {com}")

        self.root.after(0, self._set_status, "扔球中")
        while self._throw_active:
            if not self._throw_active:
                break
            if self._bridge and self._bridge.is_connected():
                self._bridge.send("MOUSE_LEFT", 200)
                time.sleep(0.15)
                self._bridge.send("LSHIFT", 50)
                time.sleep(0.05)

    def _on_monitor_screenshot(self, image_bgr: np.ndarray):
        self._box_count += 1
        self._last_shot_bgr = image_bgr
        self._display_image(image_bgr)

    # ── 区域选择 ──────────────────────────────────

    def _pick_region(self, prompt: str, on_apply: Callable[[Region], None]):
        if not self._ensure_not_monitoring():
            return
        self._set_status(prompt)
        self.root.withdraw()

        def on_selected(region: Region):
            self.root.deiconify()
            on_apply(region)

        select_region(on_selected, lambda: (self.root.deiconify(), self._set_status("已取消")))

    def _pick_template(self):
        def apply(region: Region):
            self._set_template_region(region)
            self._persist_settings()
            if self.matcher and self.matcher.is_valid:
                self._set_status(f"监控区 OK · {self.matcher.tpl_stroke_pixels}px")
            else:
                self._set_status("笔画不足")

        self._pick_region("框选监控区…", apply)

    def _pick_region_b(self):
        def apply(region: Region):
            self.region_b = region
            self._persist_settings()
            self._set_status("截图区 OK")

        self._pick_region("框选截图区…", apply)

    def _preview_template(self):
        if not self.template_region:
            messagebox.showerror("提示", "请先选择监控区域。")
            return
        self._rebuild_matcher()
        if not self.matcher or not self.matcher.is_valid:
            messagebox.showerror("提示", "笔画结构不足，请重新框选或调低亮度。")
            return
        self._display_image(gray_to_bgr(self.matcher.tpl_mask))

    def _test_match(self):
        if not self.template_region:
            messagebox.showerror("错误", "请先选择监控区域。")
            return
        self._rebuild_matcher()
        if not self.matcher or not self.matcher.is_valid:
            messagebox.showerror("错误", "笔画结构不足，请重新框选或调低亮度。")
            return
        try:
            threshold = float(self.settings_page.entry_threshold.get())
        except ValueError:
            messagebox.showerror("错误", "阈值必须是有效数字。")
            return
        result = self.matcher.analyze(grab_region(self.template_region), threshold)
        state = "强" if result.strong_present else "弱" if result.weak_present else "无"
        self._set_status(f"测试 {state} · {result.score:.2f}")

    # ── 模板管理 ──────────────────────────────────

    def _set_template_region(self, region: Region):
        self.template_region = region
        try:
            self.template_bgr = grab_region(region)
            self._rebuild_matcher()
        except Exception:
            self.template_bgr = None
            self.matcher = None

    def _rebuild_matcher(self):
        brightness = self._get_brightness()
        self.matcher = (
            WhiteTextMatcher(self.template_bgr, brightness)
            if self.template_bgr is not None else None
        )

    def _get_brightness(self) -> int:
        try:
            return int(self.settings_page.entry_brightness.get())
        except ValueError:
            return 200

    # ── 配置持久化 ────────────────────────────────

    def _current_config(self) -> AppConfig:
        return AppConfig(
            delay=self.settings_page.entry_delay.get(),
            threshold=self.settings_page.entry_threshold.get(),
            brightness=self.settings_page.entry_brightness.get(),
            trigger_delay=self.settings_page.entry_trigger.get(),
            com_port=self.settings_page.entry_com.get(),
            template_region=self.template_region,
            region_b=self.region_b,
        )

    def _persist_settings(self):
        save_config(self._current_config(), self.template_bgr)

    def _load_settings(self):
        cfg = load_config()
        for key, entry in (
            ("delay", self.settings_page.entry_delay),
            ("threshold", self.settings_page.entry_threshold),
            ("brightness", self.settings_page.entry_brightness),
            ("trigger_delay", self.settings_page.entry_trigger),
            ("com_port", self.settings_page.entry_com),
        ):
            entry.delete(0, "end")
            entry.insert(0, getattr(cfg, key))

        restored = []
        if cfg.template_region:
            self.template_region = cfg.template_region
            self.template_bgr = load_template_image()
            if self.template_bgr is None:
                self._set_template_region(cfg.template_region)
            else:
                self._rebuild_matcher()
            restored.append("监控")
        if cfg.region_b:
            self.region_b = cfg.region_b
            restored.append("截图")

        if not restored:
            return
        parts = " · ".join(restored)
        if self.matcher and self.matcher.is_valid and self.region_b:
            self._set_status(f"已恢复 {parts}")
        elif cfg.template_region:
            self._set_status(f"已恢复 {parts}，模板无效")
        else:
            self._set_status(f"已恢复 {parts}")

    # ── 关闭 ──────────────────────────────────────

    def _on_close(self):
        if self.monitor:
            self.monitor.stop()
        if self._throw_active:
            self._throw_active = False
        if self._bridge:
            self._bridge.disconnect()
        self._persist_settings()
        self.root.destroy()
