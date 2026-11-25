"""Music worker lifecycle and timing tests; no real serial ports or user songs."""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.features import FeatureContext
from backend.features.music import MusicBusyError, MusicFeature
from backend.music.compiler import compile_song
from backend.music.library import MusicLibrary
from backend.music.scheduler import TimelineClock
from test_music_domain import one_note, source


class FakeConfig:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return dict(self.data.get(key, {}))

    def update(self, key, values):
        self.data.setdefault(key, {}).update(values)
        return self.get(key)


class FakeController:
    def __init__(self, modern=True, max_keys=9, now=time.monotonic):
        self.modern = modern
        self.max_keys = max_keys
        self.connected = False
        self.owner = None
        self.session = None
        self.events = []
        self.now = now
        self.after_send = None

    def acquire(self, owner):
        if self.owner is not None and self.owner != owner:
            return False
        self.owner = owner
        return True

    def release(self, owner):
        if owner == self.owner:
            self.events.append(("release", owner, self.now()))
            self.owner = None

    def connect(self, port="AUTO", owner="manual"):
        self.connected = True
        return True

    def is_connected(self):
        return self.connected

    def capabilities(self):
        return {"protocol": 2 if self.modern else 1, "max_keys": self.max_keys if self.modern else 1, "state": self.modern}

    def begin_music(self, session):
        if self.owner != "music":
            return False
        self.session = session
        self.events.append(("begin", session, self.now()))
        return True

    def end_music(self, session):
        self.events.append(("end", session, self.now()))
        if self.session == session:
            self.session = None

    def send_state(self, session, seq, mask):
        if self.owner != "music" or session != self.session:
            return False
        self.events.append(("state", session, seq, mask, self.now()))
        if self.after_send:
            self.after_send(mask)
        return True

    def heartbeat(self, session):
        self.events.append(("heartbeat", session, self.now()))
        return self.owner == "music" and session == self.session

    def send(self, key, hold_ms, owner="manual"):
        if owner != self.owner:
            return False
        self.events.append(("key", key, hold_ms, self.now()))
        return True


def wait_until(predicate, timeout=1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.005)
    return bool(predicate())


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        path = Path(self.temporary.name)
        self.library = MusicLibrary(path / "music", path / "scores")
        self.controller = FakeController()
        self.feature = MusicFeature(FeatureContext(self.controller, Mock(), FakeConfig()), self.library)
        self.feature.COUNTDOWN_SECS = 0
        self.addCleanup(self.feature.stop)

    def add_song(self, name="song.mid", pitch=64, duration=480):
        return self.library.import_file(name, one_note(pitch, duration))["song"]["id"]

    def test_selection_only_changes_browser_choice_until_explicit_play(self):
        first = self.add_song("a.mid", 64)
        second = self.add_song("b.mid", 65)
        self.feature.set_mode("single")
        self.feature.play(first)
        self.assertTrue(wait_until(lambda: any(e[0] == "state" and e[3] for e in self.controller.events)))
        self.feature.select_song(second)
        state = self.feature.state()
        self.assertEqual(state["selected_song_id"], second)
        self.assertEqual(state["playing_song_id"], first)
        self.assertEqual(len([e for e in self.controller.events if e[0] == "begin"]), 1)
        self.feature.play(second)
        self.assertTrue(wait_until(lambda: self.feature.state()["playing_song_id"] == second))
        self.assertTrue(wait_until(lambda: len([e for e in self.controller.events if e[0] == "begin"]) == 2))
        first_session = next(e[1] for e in self.controller.events if e[0] == "begin")
        end_index = next(i for i, e in enumerate(self.controller.events) if e[:2] == ("end", first_session))
        self.assertFalse(any(e[0] == "state" and e[1] == first_session for e in self.controller.events[end_index + 1:]))

    def test_pause_releases_and_resume_does_not_restrike_already_sounded_note(self):
        ident = self.add_song()
        self.feature.set_mode("single")
        self.feature.play(ident)
        self.assertTrue(wait_until(lambda: any(e[0] == "state" and e[3] for e in self.controller.events)))
        self.feature.pause()
        self.assertTrue(wait_until(lambda: any(e[0] == "end" for e in self.controller.events)))
        frozen = self.feature._clock.position_us()
        time.sleep(.07)
        self.assertEqual(self.feature._clock.position_us(), frozen)
        self.feature.resume()
        self.assertTrue(wait_until(lambda: len([e for e in self.controller.events if e[0] == "begin"]) == 2))
        time.sleep(.08)
        nonzero = [e for e in self.controller.events if e[0] == "state" and e[3]]
        self.assertEqual(len(nonzero), 1)

    def test_stop_interrupts_countdown_and_does_not_send_or_reopen_device(self):
        ident = self.add_song()
        self.feature.COUNTDOWN_SECS = 30
        self.feature.play(ident)
        self.assertTrue(wait_until(lambda: self.feature.state()["phase"] == "countdown"))
        started = time.monotonic()
        self.feature.stop()
        self.assertLess(time.monotonic() - started, .3)
        self.assertIsNone(self.controller.owner)
        self.assertFalse(any(e[0] == "state" for e in self.controller.events))
        self.assertTrue(self.controller.connected)

    def test_legacy_device_plays_midi_and_txt_using_single_key_commands(self):
        self.controller.modern = False
        ident = self.add_song()
        self.feature.set_mode("single")
        self.feature.play(ident)
        self.assertTrue(wait_until(lambda: self.feature.state()["phase"] == "finished"))
        self.assertTrue(any(e[0] == "key" for e in self.controller.events))
        self.assertTrue(wait_until(lambda: self.controller.owner is None))
        self.controller.events.clear()
        txt = self.library.import_file("old.txt", b"B 30\nF 20\n")["song"]["id"]
        self.feature.set_mode("single")
        self.feature.play(txt)
        self.assertTrue(wait_until(lambda: self.feature.state()["phase"] == "finished"))
        self.assertEqual([e[1:3] for e in self.controller.events if e[0] == "key"], [("B", 50), ("F", 50)])

    def test_owner_conflict_and_thread_start_failure_release_cleanly(self):
        ident = self.add_song()
        self.controller.owner = "throw"
        with self.assertRaises(MusicBusyError):
            self.feature.play(ident)
        self.controller.owner = None
        with patch("backend.features.music.threading.Thread.start", side_effect=RuntimeError("cannot start")):
            with self.assertRaises(RuntimeError):
                self.feature.play(ident)
        self.assertIsNone(self.controller.owner)
        self.assertIsNone(self.feature._thread)

    def test_disconnect_fails_closed_and_releases_owner(self):
        ident = self.add_song()
        self.controller.send_state = Mock(return_value=False)
        self.feature.play(ident)
        self.assertTrue(wait_until(lambda: self.feature.state()["phase"] == "error"))
        self.assertTrue(wait_until(lambda: self.controller.owner is None))
        self.assertTrue(any(e[0] == "end" for e in self.controller.events))

    def test_all_modes_choose_correct_automatic_successor(self):
        first = self.add_song("a.mid", 64)
        second = self.add_song("b.mid", 65)
        self.feature.refresh_library()
        for mode, expected in (("sequential", None), ("single", None), ("repeat_one", second), ("repeat_all", first), ("shuffle", first)):
            self.feature.set_mode(mode)
            self.assertEqual(self.feature._next(second, 1, automatic=True), expected)
        self.feature.set_mode("sequential")
        self.assertEqual(self.feature._next(first, 1, automatic=True), second)

    def test_sequential_mode_really_starts_next_song_and_releases_after_last(self):
        first = self.add_song("a.mid", 64, duration=48)
        self.add_song("b.mid", 65, duration=48)
        self.feature.play(first)
        self.assertTrue(wait_until(lambda: self.feature.state()["phase"] == "finished"))
        self.assertTrue(wait_until(lambda: self.controller.owner is None))
        self.assertEqual([e[3] for e in self.controller.events if e[0] == "state" and e[3]], [2, 4])
        self.assertEqual(len([e for e in self.controller.events if e[0] == "begin"]), 2)

    def test_state_polling_never_reparses_and_full_state_is_broadcast(self):
        ident = self.add_song()
        self.feature.refresh_library()
        self.feature.detail(ident)
        with patch.object(self.library, "_parse", side_effect=AssertionError("Unexpected parse")):
            for _ in range(25):
                self.feature.state()
        self.feature.set_mode("single")
        calls = self.feature.ctx.bus.publish_event.call_args_list
        snapshots = [call.args[1] for call in calls if call.args[0] == "music.state"]
        self.assertTrue(snapshots)
        self.assertEqual(snapshots[-1]["mode"], "single")


class SimulatedTime:
    def __init__(self):
        self.value = 100.

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class SimulatedCondition:
    def __init__(self, clock):
        self.clock = clock
        self.waits = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def wait(self, seconds):
        self.waits += 1
        if self.waits > 10_000:
            raise AssertionError("Scheduler stopped advancing")
        self.clock.advance(max(seconds, .000001))

    def notify_all(self):
        pass


class SchedulingTests(unittest.TestCase):
    def run_timeline(self, song, latency, rapid_pause=False):
        simulated = SimulatedTime()
        controller = FakeController(now=simulated.now)
        controller.acquire("music")
        controller.connect()
        feature = MusicFeature(FeatureContext(controller, Mock(), FakeConfig()))
        feature._thread = Mock()
        feature._thread.is_alive.return_value = True
        feature._condition = SimulatedCondition(simulated)
        paused_once = [False]

        def sent(mask):
            simulated.advance(latency)
            if rapid_pause and mask and not paused_once[0]:
                paused_once[0] = True
                feature.pause()
                feature.resume()

        controller.after_send = sent
        self.last_controller = controller
        performance = compile_song(song)
        with patch("backend.features.music.time.monotonic", side_effect=simulated.now), \
                patch("backend.features.music.TimelineClock", side_effect=lambda: TimelineClock(simulated.now)):
            result = feature._perform(performance, 0, True)
        return result, controller.events

    def test_small_write_latency_preserves_minimum_hold_without_accumulating_tempo_drift(self):
        parsed = source([(0, 64, 0, 0, 90), (200_000, 65, 0, 0, 90), (400_000, 67, 0, 0, 90)])
        result, events = self.run_timeline(parsed, .007)
        self.assertTrue(result)
        frames = [e for e in events if e[0] == "state"]
        down = [e for e in frames if e[3]]
        self.assertAlmostEqual(down[1][4] - down[0][4], .2, places=5)
        self.assertAlmostEqual(down[2][4] - down[0][4], .4, places=5)
        for on, off in zip(frames[::2], frames[1::2]):
            self.assertGreaterEqual(off[4] - on[4], .05)

    def test_long_stall_continues_and_plays_every_queued_note(self):
        parsed = source([(0, 64, 0, 0, 90), (100_000, 65, 0, 0, 90), (200_000, 67, 0, 0, 90)])
        completed, events = self.run_timeline(parsed, .25)
        self.assertTrue(completed)
        self.assertEqual(len([e for e in events if e[0] == "state" and e[3]]), 3)
        self.assertIsNone(self.last_controller.session)

    def test_close_retriggers_still_get_actual_ten_ms_release(self):
        parsed = source([(0, 64, 0, 0, 90), (60_000, 64, 0, 0, 90), (120_000, 64, 0, 0, 90)])
        _, events = self.run_timeline(parsed, .001)
        frames = [e for e in events if e[0] == "state"]
        self.assertGreaterEqual(frames[2][4] - frames[1][4], .01)
        self.assertGreaterEqual(frames[4][4] - frames[3][4], .01)

    def test_rapid_pause_resume_before_worker_observes_it_does_not_freeze(self):
        parsed = source([(0, 64, 0, 0, 90), (200_000, 65, 0, 0, 90)])
        completed, events = self.run_timeline(parsed, .001, rapid_pause=True)
        self.assertTrue(completed)
        self.assertEqual(len([e for e in events if e[0] == "state" and e[3]]), 2)

    def test_long_silence_keeps_session_alive_with_heartbeats(self):
        parsed = source([(0, 64, 0, 0, 90), (2_000_000, 65, 0, 0, 90)])
        completed, events = self.run_timeline(parsed, 0)
        self.assertTrue(completed)
        pings = [e[2] for e in events if e[0] == "heartbeat"]
        self.assertGreaterEqual(len(pings), 5)
        self.assertTrue(all(b - a <= .401 for a, b in zip(pings, pings[1:])))


if __name__ == "__main__":
    unittest.main()
