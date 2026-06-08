"""CustomTkinter 主窗口。"""

from typing import Optional

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image
from tkinter import messagebox

from loco_box.capture import Region, grab_region
from loco_box.matcher import WhiteTextMatcher
from loco_box.monitor import MonitorThread
from loco_box.region_selector import select_region
from loco_box.settings import (
    load_settings,
    load_template_image,
    parse_saved_regions,
    save_settings,
    save_template_image,
)
from loco_box.ui.theme import (
    BUTTON_HEIGHT,
    COLORS,
    CORNER_RADIUS,
    FONT,
    PREVIEW_H,
    PREVIEW_W,
    ACTION_BTN_W,
    BTN_GAP,
    H_PAD,
    ROW_GAP,
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

        self._build_ui()
        self._load_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        root = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        root.pack(fill="both", expand=True, padx=0, pady=0)

        toolbar = ctk.CTkFrame(root, fg_color="transparent")
        toolbar.pack(fill="x", padx=H_PAD, pady=(10, 8))
        for col in range(4):
            toolbar.grid_columnconfigure(col, weight=1, uniform="toolbar")

        tool_btns = [
            ("监控区域", self._pick_template),
            ("截图区域", self._pick_region_b),
            ("预览", self._preview_template),
            ("测试", self._test_match),
        ]
        half_gap = BTN_GAP // 2
        for col, (text, cmd) in enumerate(tool_btns):
            btn = self._ghost_button(toolbar, text, cmd, width=TOOL_BTN_W)
            btn.grid(
                row=0,
                column=col,
                sticky="ew",
                padx=(0, half_gap) if col == 0 else (half_gap, 0 if col == 3 else half_gap),
            )

        self.btn_start = self._green_button(toolbar, "开始", self._start, width=ACTION_BTN_W)
        self.btn_start.grid(
            row=1, column=0, columnspan=2, sticky="ew",
            pady=(ROW_GAP, 0), padx=(0, BTN_GAP // 2),
        )
        self.btn_stop = self._ghost_button(toolbar, "停止", self._stop, width=ACTION_BTN_W)
        self.btn_stop.grid(
            row=1, column=2, columnspan=2, sticky="ew",
            pady=(ROW_GAP, 0), padx=(BTN_GAP // 2, 0),
        )
        self._set_monitor_buttons(running=False)

        # 参数卡片
        params_card = ctk.CTkFrame(
            root,
            fg_color=COLORS["surface"],
            corner_radius=CORNER_RADIUS,
            border_width=1,
            border_color=COLORS["border"],
        )
        params_card.pack(fill="x", padx=H_PAD, pady=(0, 8))
        params_inner = ctk.CTkFrame(params_card, fg_color="transparent")
        params_inner.pack(fill="x", padx=10, pady=8)
        self.entry_delay = self._param_field(params_inner, "延迟", "1", 36)
        self.entry_threshold = self._param_field(params_inner, "阈值", "0.45", 44)
        self.entry_brightness = self._param_field(params_inner, "亮度", "200", 36)

        # 区域信息
        self.lbl_regions = ctk.CTkLabel(
            root,
            text="监控: 未设置  ·  截图: 未设置",
            font=(FONT, 11),
            text_color=COLORS["text_muted"],
            anchor="w",
        )
        self.lbl_regions.pack(fill="x", padx=H_PAD, pady=(0, 4))

        # 状态行（固定高度，避免文字变化导致窗口抖动）
        status_frame = ctk.CTkFrame(root, height=STATUS_HEIGHT, fg_color="transparent")
        status_frame.pack(fill="x", padx=H_PAD, pady=(0, 2))
        status_frame.pack_propagate(False)
        self.lbl_status = ctk.CTkLabel(
            status_frame,
            text="就绪",
            font=(FONT, 11),
            text_color=COLORS["text_muted"],
            anchor="nw",
            wraplength=PREVIEW_W,
            justify="left",
        )
        self.lbl_status.pack(fill="both", expand=True, anchor="nw")

        # 预览区
        self.preview_frame = ctk.CTkFrame(
            root,
            width=PREVIEW_W,
            height=PREVIEW_H,
            fg_color=COLORS["preview_bg"],
            corner_radius=CORNER_RADIUS,
            border_width=1,
            border_color=COLORS["border"],
        )
        self.preview_frame.pack(padx=H_PAD, pady=(0, 12))
        self.preview_frame.pack_propagate(False)

        self.preview_label = ctk.CTkLabel(
            self.preview_frame,
            text="暂无截图",
            text_color=COLORS["text_muted"],
            font=(FONT, 12),
            fg_color="transparent",
        )
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")

        self.update_idletasks()
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")

    def _ghost_button(self, parent, text: str, command, width: int = 70) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=BUTTON_HEIGHT,
            fg_color=COLORS["surface_raised"],
            hover_color=COLORS["border"],
            text_color=COLORS["text"],
            corner_radius=6,
            font=(FONT, 12),
            border_width=1,
            border_color=COLORS["border"],
        )

    def _green_button(self, parent, text: str, command, width: int = 90) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=BUTTON_HEIGHT,
            fg_color=COLORS["green"],
            hover_color=COLORS["green_hover"],
            text_color="#ffffff",
            corner_radius=6,
            font=(FONT, 12, "bold"),
        )

    def _set_monitor_buttons(self, running: bool):
        if running:
            self.btn_start.configure(
                state="disabled",
                fg_color=COLORS["surface_raised"],
                hover_color=COLORS["border"],
                text_color=COLORS["text_muted"],
                border_width=1,
                border_color=COLORS["border"],
            )
            self.btn_stop.configure(
                state="normal",
                fg_color=COLORS["danger"],
                hover_color=COLORS["danger_hover"],
                text_color="#ffffff",
                border_width=0,
            )
        else:
            self.btn_start.configure(
                state="normal",
                fg_color=COLORS["green"],
                hover_color=COLORS["green_hover"],
                text_color="#ffffff",
                border_width=0,
            )
            self.btn_stop.configure(
                state="disabled",
                fg_color=COLORS["surface_raised"],
                hover_color=COLORS["border"],
                text_color=COLORS["text_muted"],
                border_width=1,
                border_color=COLORS["border"],
            )

    def _param_field(self, parent, label: str, default: str, width: int) -> ctk.CTkEntry:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(side="left")
        ctk.CTkLabel(
            wrap, text=label, font=(FONT, 11), text_color=COLORS["text_muted"], width=32
        ).pack(side="left")
        entry = ctk.CTkEntry(
            wrap,
            width=width,
            height=26,
            corner_radius=6,
            fg_color=COLORS["surface_raised"],
            border_color=COLORS["border"],
            border_width=1,
            font=(FONT, 12),
            justify="center",
        )
        entry.insert(0, default)
        entry.pack(side="left", padx=(2, 10))
        return entry

    def _set_status(self, text: str):
        self.lbl_status.configure(text=text)

    @staticmethod
    def _set_entry(entry: ctk.CTkEntry, value: str):
        entry.delete(0, "end")
        entry.insert(0, value)

    def _persist_settings(self):
        save_settings(
            template_region=self.template_region,
            region_b=self.region_b,
            delay=self.entry_delay.get(),
            threshold=self.entry_threshold.get(),
            brightness=self.entry_brightness.get(),
        )
        if self.template_bgr is not None:
            save_template_image(self.template_bgr)

    def _set_template_from_bgr(self, region: Region, bgr: np.ndarray):
        self.template_region = region
        self.template_bgr = bgr
        self._rebuild_matcher()
        save_template_image(bgr)

    def _apply_template_region(self, region: Region):
        try:
            self._set_template_from_bgr(region, grab_region(region))
        except Exception:
            self.template_region = region
            self.template_bgr = None
            self.matcher = None

    def _load_settings(self):
        data = load_settings()
        if not data:
            return

        for key, entry in (
            ("delay", self.entry_delay),
            ("threshold", self.entry_threshold),
            ("brightness", self.entry_brightness),
        ):
            if key in data:
                self._set_entry(entry, str(data[key]))

        template_region, region_b = parse_saved_regions(data)
        restored = []

        if template_region:
            self.template_region = template_region
            saved_template = load_template_image()
            if saved_template is not None:
                self.template_bgr = saved_template
                self._rebuild_matcher()
            else:
                self._apply_template_region(template_region)
            restored.append("监控")

        if region_b:
            self.region_b = region_b
            restored.append("截图")

        if restored:
            self._update_region_labels()
            parts = " · ".join(restored)
            ready = (
                self.template_region is not None
                and self.region_b is not None
                and self.matcher is not None
                and self.matcher.is_valid
            )
            if ready:
                self._set_status(f"已恢复上次配置 ({parts})，可直接开始")
            elif template_region:
                self._set_status(f"已恢复区域 ({parts})，模板无效请重新框选监控区域")
            else:
                self._set_status(f"已恢复上次配置 ({parts})")

    @staticmethod
    def _fmt_region(region: Region) -> str:
        return f"{region['width']}×{region['height']}"

    def _update_region_labels(self):
        mon = self._fmt_region(self.template_region) if self.template_region else "未设置"
        shot = self._fmt_region(self.region_b) if self.region_b else "未设置"
        self.lbl_regions.configure(text=f"监控: {mon}  ·  截图: {shot}")

    def _display_image(self, image_bgr: np.ndarray):
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        scale = min(PREVIEW_W / pil_img.width, PREVIEW_H / pil_img.height)
        new_w = max(1, int(pil_img.width * scale))
        new_h = max(1, int(pil_img.height * scale))
        pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        bg_rgb = tuple(int(COLORS["preview_bg"].lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
        canvas = Image.new("RGB", (PREVIEW_W, PREVIEW_H), bg_rgb)
        canvas.paste(pil_img, ((PREVIEW_W - new_w) // 2, (PREVIEW_H - new_h) // 2))

        self._preview_image = ctk.CTkImage(
            light_image=canvas,
            dark_image=canvas,
            size=(PREVIEW_W, PREVIEW_H),
        )
        self.preview_label.configure(image=self._preview_image, text="")
        self.attributes("-topmost", True)
        self.lift()

    def _pick_template(self):
        if self.monitor and self.monitor.is_running():
            messagebox.showwarning("提示", "请先停止监控再修改区域。")
            return
        self._set_status("请框选监控区域...")
        self.withdraw()

        def on_selected(region):
            self.deiconify()
            self._apply_template_region(region)
            self._update_region_labels()
            self._persist_settings()
            if self.matcher and self.matcher.is_valid:
                self._set_status(
                    f"监控区域已设置 · 笔画 {self.matcher.tpl_stroke_pixels} · "
                    f"块 {self.matcher.tpl_char_count}"
                )
            else:
                self._set_status("笔画不足，请框紧五个白字或调低亮度")

        def on_cancel():
            self.deiconify()
            self._set_status("已取消")

        select_region(on_selected, on_cancel)

    def _pick_region_b(self):
        if self.monitor and self.monitor.is_running():
            messagebox.showwarning("提示", "请先停止监控再修改区域。")
            return
        self._set_status("请框选截图区域...")
        self.withdraw()

        def on_selected(region):
            self.deiconify()
            self.region_b = region
            self._update_region_labels()
            self._persist_settings()
            self._set_status("截图区域已设置")

        def on_cancel():
            self.deiconify()
            self._set_status("已取消")

        select_region(on_selected, on_cancel)

    def _get_brightness(self) -> int:
        try:
            return int(self.entry_brightness.get())
        except ValueError:
            return 200

    def _get_threshold(self) -> float:
        return float(self.entry_threshold.get())

    def _rebuild_matcher(self):
        if self.template_bgr is None:
            self.matcher = None
            return
        self.matcher = WhiteTextMatcher(self.template_bgr, self._get_brightness())

    def _preview_template(self):
        if self.template_bgr is None:
            messagebox.showwarning("提示", "请先选择监控区域。")
            return
        self._rebuild_matcher()
        preview = cv2.cvtColor(self.matcher.tpl_mask, cv2.COLOR_GRAY2BGR)
        self._display_image(preview)
        self._set_status(
            f"笔画预览 · 像素 {self.matcher.tpl_stroke_pixels} · 块 {self.matcher.tpl_char_count}"
        )

    def _test_match(self):
        if self.template_region is None:
            messagebox.showwarning("提示", "请先选择监控区域。")
            return
        self._rebuild_matcher()
        if not self.matcher.is_valid:
            messagebox.showerror("提取失败", "笔画结构不足，请重新框选或调低亮度。")
            return
        try:
            threshold = self._get_threshold()
        except ValueError:
            messagebox.showerror("错误", "阈值必须是有效数字。")
            return

        frame = grab_region(self.template_region)
        result = self.matcher.analyze(frame, threshold)
        if result.strong_present:
            state = "强匹配"
        elif result.weak_present:
            state = "弱匹配"
        else:
            state = "未匹配"
        self._set_status(f"测试 · {state} · {result.detail}")

    def _validate_ready(self) -> bool:
        if self.template_region is None:
            messagebox.showerror("错误", "请先选择监控区域。")
            return False
        self._rebuild_matcher()
        if not self.matcher or not self.matcher.is_valid:
            messagebox.showerror("错误", "笔画结构不足，请重新框选或调低亮度。")
            return False
        if self.region_b is None:
            messagebox.showerror("错误", "请先选择截图区域。")
            return False
        return True

    def _start(self):
        if not self._validate_ready():
            return
        try:
            delay = float(self.entry_delay.get())
            threshold = self._get_threshold()
        except ValueError:
            messagebox.showerror("错误", "延迟和阈值必须是有效数字。")
            return
        if delay < 0:
            messagebox.showerror("错误", "延迟不能为负数。")
            return

        if self.monitor:
            self.monitor.stop()

        self.monitor = MonitorThread(
            region_a=self.template_region,
            region_b=self.region_b,
            matcher=self.matcher,
            delay_sec=delay,
            threshold=threshold,
            on_screenshot=lambda img: self.after(0, self._show_screenshot, img),
            on_status=lambda msg: self.after(0, self._on_status_update, msg),
            on_error=lambda msg: self.after(0, self._on_monitor_error, msg),
        )
        self._persist_settings()
        self.monitor.start()
        self._set_monitor_buttons(running=True)
        self._set_status("监控已启动")

    def _stop(self):
        if self.monitor:
            self.monitor.stop()
        self._set_monitor_buttons(running=False)
        self._set_status("监控已停止")

    def _on_status_update(self, msg: str):
        self._set_status(msg)

    def _show_screenshot(self, image_bgr: np.ndarray):
        self._display_image(image_bgr)

    def _on_monitor_error(self, msg: str):
        messagebox.showerror("监控错误", msg)
        self._stop()

    def _on_close(self):
        if self.monitor:
            self.monitor.stop()
        self._persist_settings()
        self.destroy()
