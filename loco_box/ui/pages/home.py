"""首页：预览框 + 开始/设置按钮 + 状态栏。"""

from typing import Optional

import customtkinter as ctk

from loco_box.image_ops import blank_preview, draw_text_top_right, render_bgr_preview
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
)


class HomePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._preview_image: Optional[ctk.CTkImage] = None
        self._build()

    # ── 构建 ──────────────────────────────────────

    def _build(self):
        # 状态栏（顶部）
        status_frame = ctk.CTkFrame(self, height=STATUS_HEIGHT, fg_color="transparent")
        status_frame.pack(fill="x", padx=H_PAD, pady=(8, 4))
        status_frame.pack_propagate(False)
        self.lbl_status = ctk.CTkLabel(
            status_frame, text="就绪", font=(FONT, 11),
            text_color=COLORS["text_muted"], anchor="w",
        )
        self.lbl_status.pack(fill="both", expand=True)

        # 预览框（中间，自动撑满）
        self.preview_frame = ctk.CTkFrame(
            self, fg_color=COLORS["preview_bg"], corner_radius=CORNER_RADIUS,
            border_width=1, border_color=COLORS["border"],
        )
        self.preview_frame.pack(fill="both", expand=True, padx=H_PAD, pady=4)

        self.preview_label = ctk.CTkLabel(
            self.preview_frame, text="暂无截图",
            text_color=COLORS["text_muted"], font=(FONT, 12), fg_color="transparent",
        )
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")

        # 按钮栏（底部）
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=H_PAD, pady=(4, 8))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)

        self.btn_start = ctk.CTkButton(
            bottom, text="开始", command=self.app._toggle_monitor,
            height=BUTTON_HEIGHT, fg_color=COLORS["green"],
            hover_color=COLORS["green_hover"], text_color="#ffffff",
            corner_radius=6, font=(FONT, 12, "bold"),
        )
        self.btn_start.grid(row=0, column=0, sticky="ew", padx=(0, BTN_GAP))

        self.btn_settings = ctk.CTkButton(
            bottom, text="设置", command=self._on_settings,
            height=BUTTON_HEIGHT, fg_color=COLORS["surface_raised"],
            hover_color=COLORS["border"], text_color=COLORS["text"],
            corner_radius=6, font=(FONT, 12),
            border_width=1, border_color=COLORS["border"],
        )
        self.btn_settings.grid(row=0, column=1, sticky="ew", padx=(BTN_GAP, 0))

    def _on_settings(self):
        if not self.app._ensure_not_monitoring():
            return
        self.app.show_page("settings")

    # ── 公开方法（App 调用）───────────────────────

    def set_status(self, text: str):
        if len(text) > 42:
            text = text[:41] + "…"
        self.lbl_status.configure(text=text)

    def set_monitor_button(self, running: bool):
        if running:
            self.btn_start.configure(
                text="停止", fg_color=COLORS["danger"],
                hover_color=COLORS["danger_hover"],
            )
        else:
            self.btn_start.configure(
                text="开始", fg_color=COLORS["green"],
                hover_color=COLORS["green_hover"],
            )

    def show_preview(self, image_bgr, paint_count: bool = False):
        canvas = render_bgr_preview(image_bgr, PREVIEW_W, PREVIEW_H, COLORS["preview_bg"])
        if paint_count:
            draw_text_top_right(canvas, str(self.app._box_count))
        self._preview_image = ctk.CTkImage(
            light_image=canvas, dark_image=canvas, size=(PREVIEW_W, PREVIEW_H),
        )
        self.preview_label.configure(image=self._preview_image, text="")

    def show_placeholder(self):
        canvas = blank_preview(PREVIEW_W, PREVIEW_H, COLORS["preview_bg"])
        self._preview_image = ctk.CTkImage(
            light_image=canvas, dark_image=canvas, size=(PREVIEW_W, PREVIEW_H),
        )
        self.preview_label.configure(image=self._preview_image, text="")
