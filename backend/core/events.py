"""事件总线：后端事件 → 广播到所有 WebSocket 连接。

后台线程（监控/功能/串口）通过 publish() 发布事件；总线用
loop.call_soon_threadsafe 把投递切到事件循环线程，避免跨线程操作
asyncio.Queue 的线程安全问题。
"""

import asyncio
import threading
from typing import Any, Dict, Optional, Set


class EventBus:
    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue] = set()
        self._preview_subscribers: Set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: Optional[asyncio.AbstractEventLoop]) -> None:
        self._loop = loop

    def subscribe(self, preview: bool = False) -> "asyncio.Queue":
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        with self._lock:
            self._subscribers.add(q)
            if preview:
                self._preview_subscribers.add(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue") -> None:
        with self._lock:
            self._subscribers.discard(q)
            self._preview_subscribers.discard(q)

    def has_subscribers(self) -> bool:
        with self._lock:
            return bool(self._subscribers)

    def has_preview_subscribers(self) -> bool:
        with self._lock:
            return bool(self._preview_subscribers)

    def publish(self, event: Dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._broadcast, event)
        except RuntimeError:
            # A worker may finish as the application event loop is closing.
            pass

    def _broadcast(self, event: Dict[str, Any]) -> None:
        with self._lock:
            is_frame = event.get("type") == "frame"
            subs = list(self._preview_subscribers if is_frame else self._subscribers)
        for q in subs:
            # Preview is expendable: never build a queue of large, stale JPEGs
            # or delay status events behind frames for a slow webview.
            if is_frame and not q.empty():
                continue
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # ── 便捷方法 ──────────────────────────────────
    def publish_status(self, text: str) -> None:
        self.publish({"type": "status", "text": text})

    def publish_event(self, name: str, data: Optional[Dict[str, Any]] = None) -> None:
        self.publish({"type": "event", "name": name, "data": data or {}})

    def publish_frame(self, b64: str) -> None:
        self.publish({"type": "frame", "data": b64})

    def publish_shot(self, b64: str, count: int) -> None:
        self.publish({"type": "shot", "data": b64, "count": count})

    def publish_count(self, count: int) -> None:
        self.publish({"type": "count", "count": count})
