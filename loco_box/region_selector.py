"""全屏区域框选。"""

import threading
import tkinter as tk
from typing import Callable, Optional

from loco_box.capture import Region


class RegionSelector:
    """全屏半透明覆盖层，拖拽框选矩形区域。"""

    def __init__(
        self,
        on_selected: Callable[[Region], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ):
        self.on_selected = on_selected
        self.on_cancel = on_cancel
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None

        self.root = tk.Tk()
        self.root.withdraw()

        self.win = tk.Toplevel(self.root)
        self.win.attributes("-fullscreen", True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.35)
        self.win.configure(cursor="crosshair")
        self.win.bind("<Escape>", self._cancel)

        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()

        self.canvas = tk.Canvas(
            self.win,
            width=screen_w,
            height=screen_h,
            highlightthickness=0,
            bg="black",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_text(
            screen_w // 2,
            40,
            text="拖拽框选区域，松开确认 | ESC 取消",
            fill="white",
            font=("Segoe UI", 16, "bold"),
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="#4ec9b0", width=2,
        )

    def _on_drag(self, event):
        if self.rect_id:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _on_release(self, event):
        x1, y1 = self.start_x, self.start_y
        x2, y2 = event.x, event.y
        left, top = min(x1, x2), min(y1, y2)
        width, height = abs(x2 - x1), abs(y2 - y1)

        self.win.destroy()
        self.root.destroy()

        if width < 5 or height < 5:
            if self.on_cancel:
                self.on_cancel()
            return

        self.on_selected({"left": left, "top": top, "width": width, "height": height})

    def _cancel(self, _event=None):
        self.win.destroy()
        self.root.destroy()
        if self.on_cancel:
            self.on_cancel()

    def run(self):
        self.root.mainloop()


def select_region(
    on_selected: Callable[[Region], None],
    on_cancel: Optional[Callable[[], None]] = None,
):
    """在独立线程中启动区域选择。"""
    threading.Thread(
        target=lambda: RegionSelector(on_selected, on_cancel).run(),
        daemon=True,
    ).start()
