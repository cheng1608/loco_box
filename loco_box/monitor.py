"""后台监控线程。"""

import threading
import time
from typing import Callable, Optional

import numpy as np

from loco_box.image_ops import grab_region
from loco_box.matcher import WhiteTextMatcher
from loco_box.types import Region


class MonitorThread:
    POLL_INTERVAL = 0.3
    CONFIRM_APPEAR = 4
    CONFIRM_ABSENT = 3

    def __init__(
        self,
        monitor_region: Region,
        shot_region: Region,
        matcher: WhiteTextMatcher,
        delay_sec: float,
        threshold: float,
        on_screenshot: Callable[[np.ndarray], None],
        on_status: Callable[[str], None],
        on_error: Callable[[str], None],
        on_box_appear: Optional[Callable[[], None]] = None,
    ):
        self.monitor_region = monitor_region
        self.shot_region = shot_region
        self.matcher = matcher
        self.delay_sec = delay_sec
        self.threshold = threshold
        self.on_screenshot = on_screenshot
        self.on_status = on_status
        self.on_error = on_error
        self.on_box_appear = on_box_appear
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        watching = False
        appear_hits = absent_hits = 0
        absent_since = 0.0

        while not self._stop.is_set():
            try:
                result = self.matcher.analyze(grab_region(self.monitor_region), self.threshold)

                if not watching:
                    appear_hits = appear_hits + 1 if result.strong_present else 0
                    if appear_hits >= self.CONFIRM_APPEAR:
                        watching, appear_hits, absent_hits = True, 0, 0
                        self.on_status("已出现，监控中")
                        if self.on_box_appear:
                            self.on_box_appear()
                    else:
                        hint = f" {appear_hits}/{self.CONFIRM_APPEAR}" if appear_hits else ""
                        self.on_status(f"等待出现{hint}")
                else:
                    if result.absent or not result.weak_present:
                        if absent_hits == 0:
                            absent_since = time.monotonic()
                        absent_hits += 1
                    else:
                        absent_hits = 0

                    if absent_hits >= self.CONFIRM_ABSENT:
                        # 延时从「第一次消失」起算，确认期计入延时
                        remaining = max(0.0, self.delay_sec - (time.monotonic() - absent_since))
                        self.on_status(f"消失确认 · {remaining:.1f}s后截图")
                        if self._stop.wait(remaining):
                            break
                        self.on_screenshot(grab_region(self.shot_region))
                        watching, appear_hits, absent_hits = False, 0, 0
                        self.on_status("截图完成")
                    else:
                        hint = f" {absent_hits}/{self.CONFIRM_ABSENT}" if absent_hits else ""
                        self.on_status(f"消失中{hint}")
            except Exception as exc:
                self.on_error(str(exc))
                break

            if self._stop.wait(self.POLL_INTERVAL):
                break

        self.on_status("已停止")
