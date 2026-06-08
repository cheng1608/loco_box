"""后台监控线程。"""

import threading
from typing import Callable, Optional

import numpy as np

from loco_box.capture import Region, grab_region
from loco_box.matcher import WhiteTextMatcher


class MonitorThread:
    """
    两阶段状态机：
    - 等待出现：须连续强匹配才认定文字在场
    - 监控消失：确认在场后检测消失并截图
    """

    POLL_INTERVAL = 0.3
    CONFIRM_APPEAR = 4
    CONFIRM_ABSENT = 3

    def __init__(
        self,
        region_a: Region,
        region_b: Region,
        matcher: WhiteTextMatcher,
        delay_sec: float,
        threshold: float,
        on_screenshot: Callable[[np.ndarray], None],
        on_status: Callable[[str], None],
        on_error: Callable[[str], None],
    ):
        self.region_a = region_a
        self.region_b = region_b
        self.matcher = matcher
        self.delay_sec = delay_sec
        self.threshold = threshold
        self.on_screenshot = on_screenshot
        self.on_status = on_status
        self.on_error = on_error
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        phase = "wait_appear"
        appear_streak = 0
        absent_streak = 0

        while not self._stop_event.is_set():
            try:
                frame = grab_region(self.region_a)
                result = self.matcher.analyze(frame, self.threshold)

                if phase == "wait_appear":
                    if result.strong_present:
                        appear_streak += 1
                    else:
                        appear_streak = 0

                    if appear_streak >= self.CONFIRM_APPEAR:
                        phase = "watch_disappear"
                        appear_streak = 0
                        absent_streak = 0
                        self.on_status(f"文字已确认 | 监控消失 | {result.detail}")
                    else:
                        hint = f" 强匹配{appear_streak}/{self.CONFIRM_APPEAR}" if appear_streak else ""
                        self.on_status(f"等待出现{hint} | {result.detail}")

                else:
                    if result.absent or not result.weak_present:
                        absent_streak += 1
                    else:
                        absent_streak = 0

                    if absent_streak >= self.CONFIRM_ABSENT:
                        self.on_status(f"确认消失 | {result.detail} | 等待 {self.delay_sec}s 后截图...")
                        if self._stop_event.wait(self.delay_sec):
                            break
                        shot = grab_region(self.region_b)
                        self.on_screenshot(shot)
                        phase = "wait_appear"
                        appear_streak = 0
                        absent_streak = 0
                        self.on_status(f"截图完成 | 等待下次出现 | {result.detail}")
                    else:
                        hint = f" 消失确认{absent_streak}/{self.CONFIRM_ABSENT}" if absent_streak else ""
                        self.on_status(f"监控消失{hint} | {result.detail}")

            except Exception as exc:
                self.on_error(str(exc))
                break

            if self._stop_event.wait(self.POLL_INTERVAL):
                break

        self.on_status("监控已停止")
