"""Runtime regressions without a desktop, serial device, or extra test packages.

Run with: .venv/Scripts/python.exe -m unittest discover -s tests -v
"""

import asyncio
import base64
import json
import socket
import subprocess
import sys
import threading
import time
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import URLError
from urllib.request import urlopen

from backend.core.events import EventBus


class ImportTests(unittest.TestCase):
    def test_import_does_not_start_threads_or_load_screen_libraries(self):
        result = subprocess.run(
            [sys.executable, "-c", (
                "import json,sys,threading; import backend.main; "
                "print(json.dumps({'threads': [t.name for t in threading.enumerate()], "
                "'heavy': [m for m in ('numpy','PIL','mss','tkinter') if m in sys.modules]}))"
            )],
            check=True, capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        self.assertEqual(data["threads"], ["MainThread"])
        self.assertEqual(data["heavy"], [])


class EventBusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bus = EventBus()
        self.bus.set_loop(asyncio.get_running_loop())

    async def test_only_explicit_preview_subscribers_receive_frames(self):
        normal = self.bus.subscribe()
        preview = self.bus.subscribe(preview=True)
        self.bus.publish_frame("jpeg")
        self.assertEqual(await asyncio.wait_for(preview.get(), 0.5), {"type": "frame", "data": "jpeg"})
        self.assertTrue(normal.empty())
        self.bus.publish_status("ready")
        for subscription in (normal, preview):
            self.assertEqual((await asyncio.wait_for(subscription.get(), 0.5))["text"], "ready")
        self.bus.unsubscribe(preview)
        self.assertFalse(self.bus.has_preview_subscribers())
        self.assertTrue(self.bus.has_subscribers())

    async def test_slow_preview_does_not_accumulate_images(self):
        preview = self.bus.subscribe(preview=True)
        for _ in range(100):
            self.bus.publish_frame("jpeg")
        self.bus.publish_status("stopped")
        await asyncio.sleep(0)
        self.assertEqual(preview.qsize(), 2)
        self.assertEqual((await preview.get())["type"], "frame")
        self.assertEqual((await preview.get())["text"], "stopped")

    async def test_worker_thread_can_deliver_events(self):
        subscription = self.bus.subscribe()
        worker = threading.Thread(target=self.bus.publish_count, args=(3,))
        worker.start()
        worker.join()
        self.assertEqual((await asyncio.wait_for(subscription.get(), 0.5))["count"], 3)

    async def test_publish_after_shutdown_is_safe(self):
        self.bus.set_loop(None)
        self.bus.publish_status("late worker")
        closed_loop = asyncio.new_event_loop()
        closed_loop.close()
        self.bus.set_loop(closed_loop)
        self.bus.publish_status("late worker")


class WebsocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_disconnect_releases_preview_subscription(self):
        from backend.api import ws

        bus = EventBus()
        incoming = asyncio.Queue()

        class Socket:
            async def accept(self):
                pass

            async def receive(self):
                return await incoming.get()

            async def send_json(self, event):
                raise AssertionError("No events should be sent")

        with patch.object(ws.state, "bus", bus):
            task = asyncio.create_task(ws.websocket_endpoint(Socket(), preview=True))
            await asyncio.sleep(0)
            self.assertTrue(bus.has_preview_subscribers())
            await incoming.put({"type": "websocket.disconnect"})
            await asyncio.wait_for(task, 0.5)
            self.assertFalse(bus.has_subscribers())
            self.assertFalse(bus.has_preview_subscribers())


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_ready_and_resources_follow_lifespan(self):
        from fastapi import Request
        from backend import main
        from backend.api.routes import health

        preview = Mock()
        feature = Mock(id="test")
        controller = Mock()
        bus = EventBus()
        request = Request({"type": "http", "app": main.app})
        with patch.object(main, "start_preview_loop", return_value=preview), \
                patch.object(main.state, "features", {"test": feature}), \
                patch.object(main.state, "arduino", controller), \
                patch.object(main.state, "bus", bus):
            async with main.lifespan(main.app):
                status = health(request)
                self.assertTrue(status["ready"])
                self.assertEqual(status["service"], "loco_box")
                self.assertEqual(status["protocol"], 1)
                self.assertEqual(bus._loop, asyncio.get_running_loop())
            self.assertFalse(health(request)["ready"])
            preview.stop.assert_called_once()
            feature.stop.assert_called_once()
            controller.disconnect.assert_called_once()
            self.assertIsNone(bus._loop)


class PreviewTests(unittest.TestCase):
    def test_idle_preview_never_captures_screen_and_stops_promptly(self):
        from backend.core.preview import start_preview_loop

        checked = threading.Event()
        bus = Mock()

        def has_preview():
            checked.set()
            return False

        bus.has_preview_subscribers.side_effect = has_preview
        with patch("backend.core.screen.grab_jpeg_b64") as capture:
            loop = start_preview_loop(bus, interval=30)
            try:
                self.assertTrue(checked.wait(0.5))
                capture.assert_not_called()
            finally:
                loop.stop()
            self.assertFalse(loop._thread.is_alive())

    def test_preview_is_resized_but_saved_shot_keeps_resolution(self):
        import numpy as np
        from PIL import Image
        from backend.core.screen import encode_jpeg_b64

        source = np.zeros((1080, 1920, 3), dtype=np.uint8)
        preview = encode_jpeg_b64(source, max_size=(960, 540))
        shot = encode_jpeg_b64(source)
        with Image.open(BytesIO(base64.b64decode(preview))) as image:
            self.assertEqual(image.size, (960, 540))
        with Image.open(BytesIO(base64.b64decode(shot))) as image:
            self.assertEqual(image.size, (1920, 1080))


class ThrowLifecycleTests(unittest.TestCase):
    def test_stop_interrupts_long_gap_without_sending_shift(self):
        from backend.features import FeatureContext
        from backend.features.throw import ThrowFeature

        sent = []
        first_key = threading.Event()

        def send(key, hold):
            sent.append(key)
            first_key.set()
            return True

        controller = SimpleNamespace(is_connected=lambda: True, send=send)
        feature = ThrowFeature(FeatureContext(controller, Mock(), Mock()))
        feature.start({"mouse_hold": 200, "mouse_gap": 30000})
        try:
            self.assertTrue(first_key.wait(0.5))
        finally:
            feature.stop()
            feature._thread.join(timeout=0.5)
        self.assertFalse(feature._thread.is_alive())
        self.assertFalse(feature.is_running())
        self.assertEqual(sent, ["MOUSE_LEFT"])


class DesktopRunnerTests(unittest.TestCase):
    def test_lazy_native_import_with_parent_pipe_open(self):
        # Reproduce the Windows Conda/OpenBLAS loader deadlock without reading
        # the desktop: importing NumPy must work while the parent pipe is idle.
        code = (
            "import os,sys,threading; "
            "from types import SimpleNamespace; "
            "from backend.runner import _parent_reader,_watch_parent; "
            "server=SimpleNamespace(started=True,should_exit=False); "
            "reader=_parent_reader(sys.stdin.buffer); "
            "threading.Thread(target=_watch_parent,args=(server,reader),daemon=True).start(); "
            "worker=threading.Thread(target=lambda:__import__('numpy')); "
            "worker.start(); worker.join(); "
            "print('native import completed',flush=True); os._exit(0)"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.addCleanup(self._cleanup, process)
        try:
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertIn(b"native import completed", process.stdout.read())
        finally:
            # Release the pipe before cleanup even if the regression reappears.
            process.stdin.close()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    def _start_runner(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, "-m", "backend.runner", "--port", str(port)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.addCleanup(self._cleanup, process)
        return process, port

    @staticmethod
    def _cleanup(process):
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()

    def test_parent_pipe_eof_shuts_down_a_running_backend(self):
        process, port = self._start_runner()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                with urlopen("http://127.0.0.1:%s/api/health" % port, timeout=0.2) as response:
                    health = json.load(response)
                if health["ready"]:
                    break
            except (URLError, OSError):
                pass
            if process.poll() is not None:
                self.fail(process.stdout.read().decode("utf-8", errors="replace"))
            time.sleep(0.03)
        else:
            self.fail("Desktop backend did not become ready")
        process.stdin.close()
        self.assertEqual(process.wait(timeout=4), 0)
        self.assertIn(b"Application shutdown complete", process.stdout.read())

    def test_parent_exit_during_startup_still_runs_lifespan_shutdown(self):
        process, _ = self._start_runner()
        process.stdin.close()
        self.assertEqual(process.wait(timeout=8), 0)
        self.assertIn(b"Application shutdown complete", process.stdout.read())


if __name__ == "__main__":
    unittest.main()
