"""CustomTkinter 主窗口。"""

from typing import Callable, Literal, Optional

import customtkinter as ctk
import numpy as np
from tkinter import messagebox

from loco_box.image_ops import blank_preview, draw_text_top_right, grab_region, gray_to_bgr, render_bgr_preview
from loco_box.matcher import WhiteTextMatcher
from loco_box.monitor import MonitorThread
from loco_box.region_selector import select_region
from loco_box.settings import AppConfig, load_config, load_template_image, save_config
from loco_box.types import Region
from loco_box.ui.theme import (
    BTN_GAP,
    BUTTON_HEIGHT,
    COLORS,
    CORNER_RADIUS,
    FONT,
    H_PAD,
    PREVIEW_H,
    PREVIEW_W,
    STATUS_HEIGHT,
    TOOL_BTN_W,
    WINDOW_ALPHA,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title("")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.attributes("-alpha", WINDOW_ALPHA)
        self.configure(fg_color=COLORS["bg"])

        self.template_region: Optional[Region] = None
        self.region_b: Optional[Region] = None
        self.template_bgr: Optional[np.ndarray] = None
        self.matcher: Optional[WhiteTextMatcher] = None
        self.monitor: Optional[MonitorThread] = None
        self._preview_image: Optional[ctk.CTkImage] = None
        self._box_count = 0
        self._show_box_count_overlay = False
        self._last_shot_bgr: Optional[np.ndarray] = None

        self._build_ui()
        self._load_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=H_PAD, pady=(10, 8))
        for col in range(5):
            toolbar.grid_columnconfigure(col, weight=1, uniform="toolbar")

        half_gap = BTN_GAP // 2
        for col, (text, cmd) in enumerate([
            ("监控区域", self._pick_template),
            ("截图区域", self._pick_region_b),
            ("预览", self._preview_template),
            ("测试", self._test_match),
        ]):
            pad = (0, half_gap) if col == 0 else (half_gap, half_gap)
            self._button(toolbar, text, cmd, TOOL_BTN_W).grid(row=0, column=col, sticky="ew", padx=pad)

        self.btn_toggle = self._button(toolbar, "开始", self._toggle_monitor, TOOL_BTN_W, style="green")
        self.btn_toggle.grid(row=0, column=4, sticky="ew", padx=(half_gap, 0))
        self._set_monitor_button(False)

        params_card = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=CORNER_RADIUS, border_width=1, border_color=COLORS["border"])
        params_card.pack(fill="x", padx=H_PAD, pady=(0, 8))
        params_inner = ctk.CTkFrame(params_card, fg_color="transparent")
        params_inner.pack(fill="x", padx=10, pady=8)
        self.entry_delay = self._param_field(params_inner, "延迟", "1", 36)
        self.entry_threshold = self._param_field(params_inner, "阈值", "0.45", 44)
        self.entry_brightness = self._param_field(params_inner, "亮度", "200", 36)

        status_frame = ctk.CTkFrame(self, height=STATUS_HEIGHT, fg_color="transparent")
        status_frame.pack(fill="x", padx=H_PAD, pady=(0, 2))
        status_frame.pack_propagate(False)
        self.lbl_status = ctk.CTkLabel(status_frame, text="就绪", font=(FONT, 11), text_color=COLORS["text_muted"], anchor="w")
        self.lbl_status.pack(fill="both", expand=True)

        self.preview_frame = ctk.CTkFrame(self, width=PREVIEW_W, height=PREVIEW_H, fg_color=COLORS["preview_bg"], corner_radius=CORNER_RADIUS, border_width=1, border_color=COLORS["border"])
        self.preview_frame.pack(padx=H_PAD, pady=(0, 12))
        self.preview_frame.pack_propagate(False)
        self.preview_label = ctk.CTkLabel(self.preview_frame, text="暂无截图", text_color=COLORS["text_muted"], font=(FONT, 12), fg_color="transparent")
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")

        self.update_idletasks()
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")

    def _button(
        self,
        parent,
        text: str,
        command,
        width: int,
        style: Literal["ghost", "green"] = "ghost",
    ) -> ctk.CTkButton:
        if style == "green":
            return ctk.CTkButton(parent, text=text, command=command, width=width, height=BUTTON_HEIGHT, fg_color=COLORS["green"], hover_color=COLORS["green_hover"], text_color="#ffffff", corner_radius=6, font=(FONT, 12, "bold"))
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=BUTTON_HEIGHT, fg_color=COLORS["surface_raised"], hover_color=COLORS["border"], text_color=COLORS["text"], corner_radius=6, font=(FONT, 12), border_width=1, border_color=COLORS["border"])

    def _toggle_monitor(self):
        if self.monitor and self.monitor.is_running():
            self._stop()
        else:
            self._start()

    def _set_monitor_button(self, running: bool):
        if running:
            self.btn_toggle.configure(text="停止", fg_color=COLORS["danger"], hover_color=COLORS["danger_hover"], text_color="#ffffff", border_width=0)
        else:
            self.btn_toggle.configure(text="开始", fg_color=COLORS["green"], hover_color=COLORS["green_hover"], text_color="#ffffff", border_width=0)

    def _param_field(self, parent, label: str, default: str, width: int) -> ctk.CTkEntry:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(side="left")
        ctk.CTkLabel(wrap, text=label, font=(FONT, 11), text_color=COLORS["text_muted"], width=32).pack(side="left")
        entry = ctk.CTkEntry(wrap, width=width, height=26, corner_radius=6, fg_color=COLORS["surface_raised"], border_color=COLORS["border"], border_width=1, font=(FONT, 12), justify="center")
        entry.insert(0, default)
        entry.pack(side="left", padx=(2, 10))
        return entry

    def _set_status(self, text: str):
        if len(text) > 42:
            text = text[:41] + "…"
        self.lbl_status.configure(text=text)

    def _show_preview_canvas(self, canvas, paint_count: Optional[bool] = None):
        if paint_count is None:
            paint_count = self._show_box_count_overlay
        if paint_count:
            draw_text_top_right(canvas, str(self._box_count))
        self._preview_image = ctk.CTkImage(light_image=canvas, dark_image=canvas, size=(PREVIEW_W, PREVIEW_H))
        self.preview_label.configure(image=self._preview_image, text="")
        self.lift()

    def _refresh_box_count_display(self):
        if self._last_shot_bgr is not None:
            self._display_image(self._last_shot_bgr)
        else:
            self._show_preview_canvas(blank_preview(PREVIEW_W, PREVIEW_H, COLORS["preview_bg"]))

    def _on_monitor_screenshot(self, image_bgr: np.ndarray):
        self._box_count += 1
        self._last_shot_bgr = image_bgr
        self._display_image(image_bgr)

    def _display_image(self, image_bgr: np.ndarray, paint_count: Optional[bool] = None):
        self._show_preview_canvas(render_bgr_preview(image_bgr, PREVIEW_W, PREVIEW_H, COLORS["preview_bg"]), paint_count)

    def _current_config(self) -> AppConfig:
        return AppConfig(
            delay=self.entry_delay.get(),
            threshold=self.entry_threshold.get(),
            brightness=self.entry_brightness.get(),
            template_region=self.template_region,
            region_b=self.region_b,
        )

    def _persist_settings(self):
        save_config(self._current_config(), self.template_bgr)

    def _get_brightness(self) -> int:
        try:
            return int(self.entry_brightness.get())
        except ValueError:
            return 200

    def _rebuild_matcher(self):
        self.matcher = WhiteTextMatcher(self.template_bgr, self._get_brightness()) if self.template_bgr is not None else None

    def _set_template_region(self, region: Region):
        self.template_region = region
        try:
            self.template_bgr = grab_region(region)
            self._rebuild_matcher()
        except Exception:
            self.template_bgr = None
            self.matcher = None

    def _load_settings(self):
        cfg = load_config()
        for key, entry in (("delay", self.entry_delay), ("threshold", self.entry_threshold), ("brightness", self.entry_brightness)):
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

    def _ensure_not_monitoring(self) -> bool:
        if self.monitor and self.monitor.is_running():
            messagebox.showwarning("提示", "请先停止监控再修改区域。")
            return False
        return True

    def _pick_region(self, prompt: str, on_apply: Callable[[Region], None]):
        if not self._ensure_not_monitoring():
            return
        self._set_status(prompt)
        self.withdraw()

        def on_selected(region: Region):
            self.deiconify()
            on_apply(region)

        select_region(on_selected, lambda: (self.deiconify(), self._set_status("已取消")))

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

    def _require_valid_matcher(self, title: str = "错误") -> bool:
        if not self.template_region:
            messagebox.showerror(title, "请先选择监控区域。")
            return False
        self._rebuild_matcher()
        if not self.matcher or not self.matcher.is_valid:
            messagebox.showerror(title, "笔画结构不足，请重新框选或调低亮度。")
            return False
        return True

    def _preview_template(self):
        if not self._require_valid_matcher("提示"):
            return
        self._display_image(gray_to_bgr(self.matcher.tpl_mask), paint_count=False)
        self._set_status(f"预览 · {self.matcher.tpl_stroke_pixels}px")

    def _test_match(self):
        if not self._require_valid_matcher():
            return
        try:
            threshold = float(self.entry_threshold.get())
        except ValueError:
            messagebox.showerror("错误", "阈值必须是有效数字。")
            return
        result = self.matcher.analyze(grab_region(self.template_region), threshold)
        state = "强" if result.strong_present else "弱" if result.weak_present else "无"
        self._set_status(f"测试 {state} · {result.score:.2f}")

    def _validate_ready(self) -> bool:
        if not self._require_valid_matcher():
            return False
        if not self.region_b:
            messagebox.showerror("错误", "请先选择截图区域。")
            return False
        return True

    def _start(self):
        if not self._validate_ready():
            return
        try:
            delay = float(self.entry_delay.get())
            threshold = float(self.entry_threshold.get())
        except ValueError:
            messagebox.showerror("错误", "延迟和阈值必须是有效数字。")
            return
        if delay < 0:
            messagebox.showerror("错误", "延迟不能为负数。")
            return

        if self.monitor:
            self.monitor.stop()

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
            on_screenshot=lambda img: self.after(0, self._on_monitor_screenshot, img),
            on_status=lambda msg: self.after(0, self._set_status, msg),
            on_error=lambda msg: self.after(0, self._on_monitor_error, msg),
        )
        self._persist_settings()
        self.monitor.start()
        self._set_monitor_button(True)
        self._set_status("监控中")

    def _stop(self):
        if self.monitor:
            self.monitor.stop()
        self._set_monitor_button(False)
        self._set_status("已停止")

    def _on_monitor_error(self, msg: str):
        messagebox.showerror("监控错误", msg)
        self._stop()

    def _on_close(self):
        if self.monitor:
            self.monitor.stop()
        self._persist_settings()
        self.destroy()
