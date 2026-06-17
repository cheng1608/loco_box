"""设置页：区域选择 + 参数配置。"""

import customtkinter as ctk

from loco_box.ui.theme import (
    BTN_GAP,
    BUTTON_HEIGHT,
    COLORS,
    CORNER_RADIUS,
    FONT,
    H_PAD,
    TOOL_BTN_W,
)


class SettingsPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._build()

    # ── 构建 ──────────────────────────────────────

    def _build(self):
        # 返回按钮
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.pack(fill="x", padx=H_PAD, pady=(10, 8))
        ctk.CTkButton(
            top_bar, text="← 返回", command=self._on_back,
            width=70, height=BUTTON_HEIGHT,
            fg_color=COLORS["surface_raised"],
            hover_color=COLORS["border"], text_color=COLORS["text"],
            corner_radius=6, font=(FONT, 12),
            border_width=1, border_color=COLORS["border"],
        ).pack(side="left")

        # 工具栏
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=H_PAD, pady=(0, 8))
        for col in range(4):
            toolbar.grid_columnconfigure(col, weight=1, uniform="toolbar")

        half_gap = BTN_GAP // 2
        for col, (text, cmd) in enumerate([
            ("监控区域", self.app._pick_template),
            ("截图区域", self.app._pick_region_b),
            ("预览", self.app._preview_template),
            ("测试", self.app._test_match),
        ]):
            pad = (0, half_gap) if col == 0 else (half_gap, half_gap)
            self._button(toolbar, text, cmd, TOOL_BTN_W).grid(
                row=0, column=col, sticky="ew", padx=pad,
            )

        # 参数区
        params_card = ctk.CTkFrame(
            self, fg_color=COLORS["surface"], corner_radius=CORNER_RADIUS,
            border_width=1, border_color=COLORS["border"],
        )
        params_card.pack(fill="x", padx=H_PAD, pady=(0, 8))
        params_inner = ctk.CTkFrame(params_card, fg_color="transparent")
        params_inner.pack(fill="x", padx=10, pady=8)

        self.entry_delay = self._param_field(params_inner, "延迟", "1", 36)
        self.entry_threshold = self._param_field(params_inner, "阈值", "0.45", 44)
        self.entry_brightness = self._param_field(params_inner, "亮度", "200", 36)
        self.entry_trigger = self._param_field(params_inner, "按键", "5.0", 36)
        self.entry_com = self._param_field(params_inner, "COM", "AUTO", 46)

    def _on_back(self):
        if not self.app._ensure_not_monitoring():
            return
        self.app._persist_settings()
        self.app.show_page("home")

    # ── 控件工厂 ──────────────────────────────────

    def _button(self, parent, text: str, command, width: int) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, command=command, width=width,
            height=BUTTON_HEIGHT, fg_color=COLORS["surface_raised"],
            hover_color=COLORS["border"], text_color=COLORS["text"],
            corner_radius=6, font=(FONT, 12),
            border_width=1, border_color=COLORS["border"],
        )

    def _param_field(self, parent, label: str, default: str, width: int) -> ctk.CTkEntry:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(side="left")
        ctk.CTkLabel(
            wrap, text=label, font=(FONT, 11),
            text_color=COLORS["text_muted"], width=32,
        ).pack(side="left")
        entry = ctk.CTkEntry(
            wrap, width=width, height=26, corner_radius=6,
            fg_color=COLORS["surface_raised"], border_color=COLORS["border"],
            border_width=1, font=(FONT, 12), justify="center",
        )
        entry.insert(0, default)
        entry.pack(side="left", padx=(2, 10))
        return entry
