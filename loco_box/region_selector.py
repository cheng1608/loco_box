"""全屏区域框选。"""

import threading
import tkinter as tk
from typing import Callable, Optional

from loco_box.types import Region


def select_region(
    on_selected: Callable[[Region], None],
    on_cancel: Optional[Callable[[], None]] = None,
):
    """在独立线程中启动区域选择。"""
    threading.Thread(target=lambda: _RegionSelector(on_selected, on_cancel).run(), daemon=True).start()


class _RegionSelector:
    def __init__(self, on_selected: Callable[[Region], None], on_cancel: Optional[Callable[[], None]]):
        self.on_selected = on_selected
        self.on_cancel = on_cancel
        self._start = (0, 0)
        self._rect_id = None

        self._root = tk.Tk()
        self._root.withdraw()
        self._win = tk.Toplevel(self._root)
        self._win.attributes("-fullscreen", True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0.35)
        self._win.configure(cursor="crosshair")
        self._win.bind("<Escape>", self._cancel)

        sw, sh = self._win.winfo_screenwidth(), self._win.winfo_screenheight()
        self._canvas = tk.Canvas(self._win, width=sw, height=sh, highlightthickness=0, bg="black")
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.create_text(sw // 2, 40, text="拖拽框选区域，松开确认 | ESC 取消", fill="white", font=("Segoe UI", 16, "bold"))
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, event):
        self._start = (event.x, event.y)
        if self._rect_id:
            self._canvas.delete(self._rect_id)
        self._rect_id = self._canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#4ec9b0", width=2)

    def _on_drag(self, event):
        if self._rect_id:
            self._canvas.coords(self._rect_id, self._start[0], self._start[1], event.x, event.y)

    def _close(self):
        self._win.destroy()
        self._root.destroy()

    def _on_release(self, event):
        x1, y1 = self._start
        left, top = min(x1, event.x), min(y1, event.y)
        width, height = abs(event.x - x1), abs(event.y - y1)
        self._close()
        if width < 5 or height < 5:
            if self.on_cancel:
                self.on_cancel()
            return
        self.on_selected({"left": left, "top": top, "width": width, "height": height})

    def _cancel(self, _event=None):
        self._close()
        if self.on_cancel:
            self.on_cancel()

    def run(self):
        self._root.mainloop()
