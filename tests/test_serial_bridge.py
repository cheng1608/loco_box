"""Transport tests use an in-memory firmware peer; no serial port is opened."""

import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.core.arduino import ArduinoController
from loco_box.serial_bridge import SerialBridge


class FirmwarePeer:
    def __init__(self, max_keys=9, legacy=False):
        self.is_open = True
        self.max_keys = max_keys
        self.legacy = legacy
        self.rx = bytearray()
        self.writes = []
        self.session = None
        self.seq = 0
        self.mask = 0
        self.ignore = set()
        self.short_write = False

    @property
    def in_waiting(self):
        return len(self.rx)

    def read(self, size):
        result = bytes(self.rx[:size])
        del self.rx[:size]
        return result

    def reply(self, line):
        self.rx.extend((line + "\n").encode("ascii"))

    def write(self, payload):
        self.writes.append(payload)
        if self.short_write:
            return len(payload) - 1
        fields = payload.decode("ascii").strip().split()
        if self.legacy or fields[0] in self.ignore:
            return len(payload)
        if fields[0] == "HELLO":
            self.reply("CAPS 2 %d 1500 2.0.0" % self.max_keys)
        elif fields[0] == "BEGIN":
            self.session, self.mask, self.seq = fields[1], 0, 0
            self.reply("OK BEGIN " + self.session)
        elif fields[0] == "STATE":
            if fields[1] != self.session:
                self.reply("ERR SESSION")
            else:
                self.seq, self.mask = int(fields[2]), int(fields[3])
        elif fields[0] == "PING":
            if fields[1] != self.session:
                self.reply("ERR SESSION")
            else:
                self.reply("OK PING %s %d" % (self.session, self.seq))
        elif fields[0] == "STOP":
            if fields[1] != self.session:
                self.reply("ERR SESSION")
            else:
                self.session, self.mask = None, 0
                self.reply("OK STOP " + fields[1])
        elif fields[0] == "PANIC":
            self.session, self.mask = None, 0
            self.reply("OK PANIC")
        return len(payload)

    def close(self):
        self.is_open = False


def bridge_for(peer):
    bridge = SerialBridge("FAKE")
    bridge._ser = peer
    bridge.ACK_TIMEOUT = 0.015
    bridge.probe_capabilities(timeout=0.01)
    return bridge


class SerialProtocolTests(unittest.TestCase):
    def test_nine_key_state_is_one_write_and_stop_invalidates_session(self):
        peer = FirmwarePeer()
        bridge = bridge_for(peer)
        self.assertEqual(bridge.capabilities()["max_keys"], 9)
        self.assertTrue(bridge.begin_music("a" * 32))
        before = len(peer.writes)
        self.assertTrue(bridge.send_state("a" * 32, 0, 511))
        self.assertEqual(len(peer.writes), before + 1)
        self.assertEqual(peer.mask, 511)
        self.assertTrue(bridge.heartbeat("a" * 32))
        bridge.end_music("a" * 32)
        self.assertEqual(peer.mask, 0)
        self.assertFalse(bridge.send_state("a" * 32, 1, 1))
        self.assertTrue(bridge.begin_music("next"))
        self.assertFalse(bridge.send_state("a" * 32, 2, 1))

    def test_legacy_probe_is_bounded_and_timed_keys_still_work(self):
        peer = FirmwarePeer(legacy=True)
        started = time.monotonic()
        bridge = bridge_for(peer)
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(bridge.capabilities()["protocol"], 1)
        self.assertTrue(bridge.send("F12", 50))
        self.assertEqual(peer.writes[-1], b"F12:50\n")
        self.assertFalse(bridge.begin_music("song"))

    def test_capacity_sequences_and_injection_are_checked_before_writing(self):
        peer = FirmwarePeer(max_keys=6)
        bridge = bridge_for(peer)
        self.assertFalse(bridge.send("B\nPANIC", 50))
        self.assertFalse(bridge.send("B", -1))
        self.assertFalse(bridge.send("B", 60001))
        self.assertFalse(bridge.begin_music("bad session"))
        self.assertTrue(bridge.begin_music("song"))
        self.assertTrue(bridge.send_state("song", 10, 63))
        before = len(peer.writes)
        self.assertFalse(bridge.send_state("song", 11, 127))
        self.assertFalse(bridge.send_state("song", 9, 0))
        self.assertFalse(bridge.send_state("song", 10, 0))
        self.assertFalse(bridge.send_state("song", True, 0))
        self.assertFalse(bridge.send_state("song", 11, 512))
        self.assertFalse(bridge.send("1", 50))
        self.assertEqual(len(peer.writes), before)
        self.assertTrue(bridge.send_state("song", 10, 63))  # safe duplicate

    def test_device_errors_and_lost_session_stop_the_stream(self):
        peer = FirmwarePeer()
        bridge = bridge_for(peer)
        self.assertTrue(bridge.begin_music("song"))
        self.assertTrue(bridge.send_state("song", 1, 7))
        peer.reply("ERR CAPACITY")
        self.assertFalse(bridge.send_state("song", 2, 0))
        self.assertIn("CAPACITY", bridge.last_error)
        self.assertTrue(bridge.panic())
        self.assertEqual(peer.mask, 0)
        self.assertTrue(bridge.begin_music("next"))
        peer.session = None  # watchdog/disconnect erased the device generation
        self.assertFalse(bridge.heartbeat("next"))
        self.assertIn("SESSION", bridge.last_error)

    def test_stop_ack_timeout_falls_back_to_panic(self):
        peer = FirmwarePeer()
        bridge = bridge_for(peer)
        self.assertTrue(bridge.begin_music("song"))
        self.assertTrue(bridge.send_state("song", 0, 511))
        peer.ignore.add("STOP")
        bridge.end_music("song")
        self.assertEqual(peer.writes[-1], b"PANIC\n")
        self.assertEqual(peer.mask, 0)

    def test_short_writes_and_oversized_responses_fail(self):
        peer = FirmwarePeer()
        bridge = bridge_for(peer)
        self.assertTrue(bridge.begin_music("song"))
        peer.short_write = True
        self.assertFalse(bridge.send_state("song", 0, 1))
        self.assertIn("Incomplete", bridge.last_error)
        self.assertFalse(bridge.is_connected())
        peer = FirmwarePeer()
        bridge = bridge_for(peer)
        self.assertTrue(bridge.begin_music("again"))
        peer.rx.extend(b"x" * (bridge.MAX_RESPONSE + 1))
        self.assertFalse(bridge.heartbeat("again"))
        self.assertIn("exceeds", bridge.last_error)

    def test_connection_is_opened_and_settled_only_once(self):
        peer = FirmwarePeer()
        bridge = SerialBridge("FAKE")
        with patch("loco_box.serial_bridge.serial.Serial", return_value=peer) as open_port, \
                patch("loco_box.serial_bridge.time.sleep") as sleep:
            self.assertTrue(bridge.connect_and_wait())
            self.assertTrue(bridge.connect_and_wait())
        open_port.assert_called_once_with("FAKE", 9600, timeout=0.02, write_timeout=0.2)
        sleep.assert_called_once_with(3.0)
        self.assertEqual(bridge.capabilities()["protocol"], 2)


class ControllerOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.peer = FirmwarePeer()
        self.controller = ArduinoController()
        self.controller._bridge = bridge_for(self.peer)

    def test_auto_port_prefers_detected_device_over_stale_saved_port(self):
        config = Mock()
        config.get_global.return_value = "COM_OLD"
        self.controller.set_config(config)
        with patch("backend.core.arduino.SerialBridge.find_arduino", return_value="COM_NEW"):
            self.assertEqual(self.controller._resolve_port("AUTO"), "COM_NEW")
        with patch("backend.core.arduino.SerialBridge.find_arduino", return_value=None):
            self.assertEqual(self.controller._resolve_port("AUTO"), "COM_OLD")
            self.assertEqual(self.controller._resolve_port("COM_MANUAL"), "COM_MANUAL")

    def test_owner_excludes_manual_and_late_worker_writes(self):
        controller = self.controller
        self.assertTrue(controller.acquire("throw"))
        self.assertFalse(controller.acquire("music"))
        self.assertFalse(controller.send("B", 50))
        self.assertFalse(controller.send("B", 50, owner="music"))
        self.assertFalse(controller.disconnect())
        self.assertTrue(controller.send("1", 50, owner="throw"))
        controller.release("music")
        self.assertEqual(controller.current_owner(), "throw")
        controller.release("throw")
        self.assertIsNone(controller.current_owner())
        self.assertEqual(self.peer.writes[-1], b"PANIC\n")
        before = len(self.peer.writes)
        self.assertFalse(controller.send("1", 50, owner="throw"))
        self.assertEqual(len(self.peer.writes), before)
        self.assertTrue(controller.send("B", 50))

    def test_session_api_requires_owner_and_forced_shutdown_releases(self):
        controller = self.controller
        self.assertFalse(controller.begin_music("song"))
        self.assertTrue(controller.acquire("music"))
        self.assertTrue(controller.begin_music("song"))
        self.assertTrue(controller.send_state("song", 0, 511))
        self.assertTrue(controller.disconnect(force=True))
        self.assertEqual(self.peer.mask, 0)
        self.assertFalse(self.peer.is_open)
        self.assertIsNone(controller.current_owner())

    def test_failed_release_closes_transport_before_owner_is_reused(self):
        self.assertTrue(self.controller.acquire("music"))
        self.assertTrue(self.controller.begin_music("song"))
        self.assertTrue(self.controller.send_state("song", 0, 511))
        self.peer.ignore.add("PANIC")
        self.controller.release("music")
        self.assertIsNone(self.controller.current_owner())
        self.assertFalse(self.controller.is_connected())
        self.assertFalse(self.controller.send("B", 50))

    def test_acquisition_is_atomic_for_competing_workers(self):
        barrier = threading.Barrier(3)
        results = []
        def acquire(owner):
            barrier.wait()
            results.append((owner, self.controller.acquire(owner)))
        threads = [threading.Thread(target=acquire, args=(owner,)) for owner in ("music", "throw")]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(1)
        winners = [owner for owner, success in results if success]
        self.assertEqual(winners, [self.controller.current_owner()])

    def test_released_worker_cannot_reopen_a_disconnected_port(self):
        controller = self.controller
        self.assertTrue(controller.acquire("box_monitor"))
        controller.release("box_monitor")
        self.assertTrue(controller.disconnect())
        with patch("backend.core.arduino.SerialBridge") as bridge_type:
            self.assertFalse(controller.connect("FAKE", owner="box_monitor"))
            bridge_type.assert_not_called()
            self.assertTrue(controller.acquire("music"))
            self.assertFalse(controller.connect("FAKE"))
            self.assertFalse(controller.connect("FAKE", owner="box_monitor"))
            bridge_type.assert_not_called()
            bridge_type.return_value.connect_and_wait.return_value = True
            self.assertTrue(controller.connect("FAKE", owner="music"))
            bridge_type.assert_called_once_with("FAKE")

    def test_manual_connect_to_owned_open_port_is_a_noop(self):
        self.assertTrue(self.controller.acquire("music"))
        with patch("backend.core.arduino.SerialBridge") as bridge_type:
            self.assertTrue(self.controller.connect("OTHER_PORT"))
            bridge_type.assert_not_called()
        self.assertEqual(self.controller.port(), "FAKE")
        self.assertEqual(self.controller.current_owner(), "music")

    def test_status_reads_do_not_wait_for_transport_lock(self):
        acquired = threading.Event()
        release = threading.Event()
        def slow_io():
            with self.controller._lock, self.controller._bridge._lock:
                acquired.set()
                release.wait(2)
        thread = threading.Thread(target=slow_io)
        thread.start()
        try:
            self.assertTrue(acquired.wait(1))
            started = time.monotonic()
            self.assertTrue(self.controller.is_connected())
            self.assertEqual(self.controller.capabilities()["max_keys"], 9)
            self.assertEqual(self.controller.port(), "FAKE")
            self.assertIsNone(self.controller.current_owner())
            self.assertLess(time.monotonic() - started, 0.1)
        finally:
            release.set()
            thread.join(1)


class NativeFirmwareTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("g++"), "g++ is required for portable firmware state tests")
    def test_state_machine_capacity_deadlines_sessions_and_watchdog(self):
        source = Path(__file__).resolve().parents[1] / "scripts/arduino_bridge/tests/state_test.cpp"
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "bridge-state-test.exe"
            subprocess.run([shutil.which("g++"), "-std=c++11", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(executable)], check=True, capture_output=True, text=True)
            result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
            self.assertIn("watchdog tests passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
