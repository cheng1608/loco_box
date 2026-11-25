"""A pauseable absolute clock; event processing cost never shifts later deadlines."""

import time
import threading
from typing import Callable


class TimelineClock:
    def __init__(self, now: Callable[[], float] = time.monotonic):
        self._now = now
        self._anchor = now()
        self._offset_us = 0
        self._paused = False
        self._lock = threading.RLock()

    def position_us(self) -> int:
        with self._lock:
            if self._paused:
                return self._offset_us
            return self._offset_us + max(0, round((self._now() - self._anchor) * 1_000_000))

    def pause(self) -> None:
        with self._lock:
            if not self._paused:
                self._offset_us = self.position_us()
                self._paused = True

    def resume(self) -> None:
        with self._lock:
            if self._paused:
                self._anchor = self._now()
                self._paused = False

    def seconds_until(self, time_us: int) -> float:
        return max(0., (time_us - self.position_us()) / 1_000_000)

    def rebase(self, position_us: int) -> None:
        """Continue from an overdue onset without dropping queued notes."""
        with self._lock:
            self._offset_us = max(0, position_us)
            self._anchor = self._now()
