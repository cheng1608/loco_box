"""全局实时预览：有订阅者时周期性截主屏推送给前端。"""

import logging
import threading

from backend.core.events import EventBus

logger = logging.getLogger(__name__)


class PreviewLoop:
    """Owned by the application lifespan; screen dependencies load on demand."""

    def __init__(self, bus: EventBus, interval: float = 0.3) -> None:
        self._bus = bus
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="screen-preview", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        region = None
        failed = False
        while not self._stop.is_set():
            if self._bus.has_preview_subscribers():
                try:
                    from backend.core.screen import grab_jpeg_b64, primary_monitor_region

                    if region is None:
                        region = primary_monitor_region()
                    if region is not None:
                        frame = grab_jpeg_b64(region, max_size=(960, 540))
                        self._bus.publish_frame(frame)
                    failed = False
                except Exception:
                    if not failed:
                        logger.exception("Screen preview failed; will retry")
                    failed = True
                    region = None
            else:
                # Redetect after reopening the preview (monitor layout may change).
                region = None
            if self._stop.wait(self._interval):
                return


def start_preview_loop(bus: EventBus, interval: float = 0.3) -> PreviewLoop:
    preview = PreviewLoop(bus, interval)
    preview.start()
    return preview
