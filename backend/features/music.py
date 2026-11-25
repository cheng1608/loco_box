"""Direct MIDI/legacy-score playback with one interruptible owner of the device."""

import math
import random
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.core.config import DATA_DIR, SCORES_DIR
from backend.core.arduino import DeviceBusyError
from backend.features import Feature, FeatureContext, register
from backend.music.legacy import parse_score
from backend.music.library import MusicLibrary
from backend.music.models import KEYS, Performance
from backend.music.scheduler import TimelineClock


class MusicBusyError(DeviceBusyError):
    pass


@register
class MusicFeature(Feature):
    id = "music"
    name = "自动演奏"
    config_schema = [
        {"key": "mode", "label": "播放模式", "type": "select", "default": "sequential"},
        {"key": "current", "label": "当前曲目", "type": "text", "default": ""},
    ]
    MODES = ("sequential", "single", "repeat_one", "repeat_all", "shuffle")
    MODE_NAMES = {"sequential": "列表播放", "single": "单曲播放", "repeat_one": "单曲循环", "repeat_all": "列表循环", "shuffle": "随机播放"}
    HOLD_MS = 50
    COUNTDOWN_SECS = 3
    REBASE_LAG_US = 100_000
    VALID_KEYS = frozenset(KEYS)
    parse_score = staticmethod(parse_score)

    def __init__(self, ctx: FeatureContext, library: Optional[MusicLibrary] = None) -> None:
        super().__init__(ctx)
        self.library = library or MusicLibrary(DATA_DIR / "music", SCORES_DIR)
        self._condition = threading.Condition(threading.RLock())
        self._thread: Optional[threading.Thread] = None
        self._finishing = False
        self._initialized = False
        self._mode = "sequential"
        self._selected = ""
        self._playing = ""
        self._playing_name = ""
        self._requested = ""
        self._generation = 0
        self._stop_requested = False
        self._paused = False
        self._phase = "stopped"
        self._position_us = 0
        self._duration_us = 0
        self._speed = 1.
        self._countdown = 0
        self._revision = 0
        self._error: Optional[Dict[str, str]] = None
        self._session: Optional[str] = None
        self._clock: Optional[TimelineClock] = None
        self._last_broadcast = 0.
        self._device: Dict[str, Any] = {"connected": False, "protocol": 0, "max_keys": 0, "midi_supported": False}

    def refresh_library(self) -> List[Dict[str, Any]]:
        songs = self.library.refresh()
        with self._condition:
            if not self._initialized:
                saved = self.ctx.config.get("music")
                self._mode = saved.get("mode") if saved.get("mode") in self.MODES else "sequential"
                candidate = str(saved.get("selected_song_id") or saved.get("current") or "")
                try:
                    self._selected = self.library.resolve(candidate)
                except ValueError:
                    self._selected = songs[0]["id"] if songs else ""
                self._initialized = True
            elif not any(s["id"] == self._selected for s in songs):
                self._selected = songs[0]["id"] if songs else ""
        return songs

    def _ensure_library(self) -> None:
        if not self._initialized:
            self.refresh_library()

    def _save_state(self) -> None:
        current = ""
        if self._selected:
            try:
                current = self.library.song(self._selected)["filename"]
            except ValueError:
                pass
        self.ctx.config.update("music", {"mode": self._mode, "selected_song_id": self._selected, "current": current})

    def is_running(self) -> bool:
        with self._condition:
            return bool(self._thread and self._thread.is_alive() and not self._stop_requested)

    def is_paused(self) -> bool:
        return self._paused

    def current_song(self) -> str:
        self._ensure_library()
        try:
            return self.library.song(self._selected)["filename"]
        except ValueError:
            return ""

    def mode(self) -> str:
        return self._mode

    def playlist(self) -> List[str]:
        self._ensure_library()
        return [song["filename"] for song in self.library.summaries()]

    def state(self) -> Dict[str, Any]:
        self._ensure_library()
        with self._condition:
            # A shared snapshot sequence orders HTTP responses against WebSocket
            # updates, including continuously changing playback position.
            self._revision += 1
            connected = self.ctx.arduino.is_connected()
            if connected:
                caps = self.ctx.arduino.capabilities()
                self._device = {"connected": True, "protocol": caps.get("protocol", 1), "max_keys": caps.get("max_keys", 1), "midi_supported": bool(caps.get("state") and caps.get("protocol", 1) >= 2)}
            else:
                self._device = {"connected": False, "protocol": 0, "max_keys": 0, "midi_supported": False}
            return {
                "playlist": self.playlist(), "current": self.current_song(), "mode": self._mode,
                "running": self.is_running(), "paused": self._paused, "phase": self._phase,
                "selected_song_id": self._selected, "playing_song_id": self._playing,
                "playing_name": self._playing_name, "position_ms": round(self._position_us / 1000),
                "duration_ms": round(self._duration_us / 1000), "speed": self._speed,
                "countdown_remaining": self._countdown, "revision": self._revision,
                "error": dict(self._error) if self._error else None, "device": dict(self._device),
            }

    def detail(self, ident: str) -> Dict[str, Any]:
        self._ensure_library()
        caps = self.ctx.arduino.capabilities() if self.ctx.arduino.is_connected() else {}
        limit = int(caps.get("max_keys", 1)) if caps else 9
        return self.library.detail(ident, limit)

    def _changed(self, text: Optional[str] = None) -> None:
        self._revision += 1
        if text:
            self.ctx.bus.publish_status(text)
        self.ctx.bus.publish_event("music_state_changed", {"revision": self._revision})
        self._broadcast(force=True)

    def _broadcast(self, force: bool = False) -> None:
        now = time.monotonic()
        if self._initialized and (force or now - self._last_broadcast >= .2):
            self._last_broadcast = now
            self.ctx.bus.publish_event("music.state", self.state())

    def select_song(self, name: str) -> bool:
        self._ensure_library()
        with self._condition:
            try:
                ident = self.library.resolve(name)
            except ValueError:
                return False
            self._selected = ident
            self._save_state()
            self._changed()
        return True

    def delete_song(self, song_id: str) -> List[Dict[str, Any]]:
        self._ensure_library()
        with self._condition:
            ident = self.library.resolve(song_id)
            if (self._thread and self._thread.is_alive()
                    and ident in (self._playing, self._requested)):
                raise MusicBusyError("请先停止这首曲目的演奏，等待设备释放后再删除")
            before = self.library.summaries()
            index = next(i for i, song in enumerate(before) if song["id"] == ident)
            removed = self.library.delete(ident)
            songs = self.library.summaries()
            if self._selected == ident:
                self._selected = songs[min(index, len(songs) - 1)]["id"] if songs else ""
            if self._requested == ident:
                self._requested = ""
            if self._playing == ident:
                self._playing = self._playing_name = ""
                self._position_us = self._duration_us = 0
                self._phase = "stopped"
                self._error = None
            self._save_state()
            self._changed("已从曲库删除：%s" % removed["name"])
            return songs

    def set_mode(self, mode: str) -> bool:
        if mode not in self.MODES:
            return False
        self._ensure_library()
        with self._condition:
            self._mode = mode
            self._save_state()
            self._changed("播放模式：%s" % self.MODE_NAMES[mode])
        return True

    def start(self, config: Dict[str, Any]) -> None:
        self._ensure_library()
        if config.get("mode") in self.MODES:
            self._mode = config["mode"]
        self.play(config.get("selected_song_id") or config.get("current") or None)

    def play(self, song_id: Optional[str] = None) -> None:
        self._ensure_library()
        ident = self.library.resolve(song_id or self._selected)
        self.library.performance(ident)
        with self._condition:
            # Recheck under the deletion lock after potentially expensive parsing.
            self.library.resolve(ident)
            if self._thread and self._thread.is_alive():
                if self._stop_requested or self._finishing:
                    raise MusicBusyError("上一轮演奏仍在释放设备，请稍后重试")
                self._selected = ident
                self._requested = ident
                self._generation += 1
                self._paused = False
                self._phase = "preparing"
                self._save_state()
                self._condition.notify_all()
                return
            if not self.ctx.arduino.acquire("music"):
                raise MusicBusyError("Arduino 正被其他功能使用，请先停止监控或丢球")
            self._selected = ident
            self._requested = ident
            self._generation += 1
            self._stop_requested = False
            self._finishing = False
            self._paused = False
            self._phase = "preparing"
            self._error = None
            self._position_us = 0
            try:
                self._save_state()
                self._changed("正在准备演奏")
                self._thread = threading.Thread(target=self._run, name="music-player", daemon=True)
                self._thread.start()
            except Exception:
                self.ctx.arduino.release("music")
                self._thread = None
                self._phase = "error"
                raise

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._generation += 1
            self._paused = False
            self._phase = "stopped"
            self._countdown = 0
            self._condition.notify_all()
            worker = self._thread
            self._changed("演奏已停止")
        if worker and worker is not threading.current_thread():
            worker.join(timeout=.5)

    def pause(self) -> None:
        with self._condition:
            if not self.is_running() or self._phase == "preparing":
                return
            self._paused = True
            if self._clock:
                self._clock.pause()
            self._phase = "paused"
            self._condition.notify_all()
            self._changed("演奏已暂停")

    def resume(self) -> None:
        with self._condition:
            if not self.is_running() or not self._paused:
                return
            self._paused = False
            self._condition.notify_all()
            self._changed("继续演奏")

    def _next(self, current: str, direction: int, automatic: bool = False) -> Optional[str]:
        ids = [song["id"] for song in self.library.summaries()]
        if not ids:
            return None
        index = ids.index(current) if current in ids else 0
        if automatic and self._mode == "single":
            return None
        if automatic and self._mode == "repeat_one":
            return current
        if self._mode == "shuffle" and direction > 0:
            return random.choice([ident for ident in ids if ident != current] or ids)
        if automatic and self._mode == "sequential" and index + 1 >= len(ids):
            return None
        return ids[(index + direction) % len(ids)]

    def _manual_advance(self, direction: int) -> None:
        self._ensure_library()
        with self._condition:
            target = self._next(self._playing if self.is_running() else self._selected, direction)
            if target:
                if self.is_running():
                    self.play(target)
                else:
                    self.select_song(target)

    def next_track(self) -> None:
        self._manual_advance(1)

    def prev_track(self) -> None:
        self._manual_advance(-1)

    def _cancelled(self, generation: int) -> bool:
        return self._stop_requested or generation != self._generation

    def _count_in(self, generation: int) -> bool:
        clock = TimelineClock()
        with self._condition:
            self._clock = clock
        total = int(self.COUNTDOWN_SECS * 1_000_000)
        while True:
            with self._condition:
                if self._cancelled(generation):
                    return False
                if self._paused:
                    clock.pause()
                    self._condition.wait(.1)
                    continue
                clock.resume()
                self._phase = "countdown"
                remaining = total - clock.position_us()
                self._countdown = max(0, math.ceil(remaining / 1_000_000))
                self._broadcast()
                if remaining <= 0:
                    return True
                self._condition.wait(min(.1, remaining / 1_000_000))

    def _begin_session(self) -> str:
        session = uuid.uuid4().hex
        if not self.ctx.arduino.begin_music(session):
            raise RuntimeError("无法建立演奏会话，请检查 Arduino 固件与连接")
        self._session = session
        return session

    def _end_session(self) -> None:
        if self._session:
            self.ctx.arduino.end_music(self._session)
            self._session = None

    def _perform(self, performance: Performance, generation: int, modern: bool, legacy: bool = False) -> bool:
        seq = 0
        index = 0
        logical_mask = suppressed_mask = 0
        was_paused = False
        physical_mask = 0
        pressed_at: Dict[int, float] = {}
        released_at: Dict[int, float] = {}
        if modern:
            self._begin_session()
        clock = TimelineClock()
        with self._condition:
            self._clock = clock
        heartbeat_at = time.monotonic() + .35
        try:
            while True:
                with self._condition:
                    if self._cancelled(generation):
                        return False
                    paused = self._paused
                    if not paused and not was_paused:
                        # Pause/resume can both arrive before the worker observes
                        # either request; do not leave its clock frozen forever.
                        clock.resume()
                    self._position_us = min(clock.position_us(), performance.duration_us)
                    self._broadcast()
                if paused:
                    if not was_paused:
                        clock.pause()
                        suppressed_mask = logical_mask
                        self._end_session()
                        physical_mask = 0
                        pressed_at.clear()
                        released_at.clear()
                        was_paused = True
                    with self._condition:
                        self._condition.wait(.1)
                    continue
                if was_paused:
                    if modern:
                        self._begin_session()
                        seq = 0
                    clock.resume()
                    heartbeat_at = time.monotonic() + .35
                    was_paused = False
                with self._condition:
                    self._phase = "playing"
                if modern and time.monotonic() >= heartbeat_at:
                    if not self.ctx.arduino.heartbeat(self._session):
                        raise RuntimeError("演奏设备已断开或会话失效")
                    heartbeat_at = time.monotonic() + .35
                position = clock.position_us()
                if index >= len(performance.events):
                    if position >= performance.duration_us:
                        return True
                    next_time = performance.duration_us
                else:
                    event = performance.events[index]
                    next_time = event.time_us
                    if position >= next_time:
                        with self._condition:
                            if self._cancelled(generation) or self._paused:
                                continue
                            next_suppressed = suppressed_mask & event.mask
                            for key in event.onset_keys:
                                next_suppressed &= ~(1 << KEYS.index(key))
                            next_mask = event.mask & ~next_suppressed
                            if modern:
                                # Absolute musical deadlines never accumulate write time.
                                # A delayed key-down still receives a full 50ms pulse.
                                now = time.monotonic()
                                earliest = now
                                for bit in range(len(KEYS)):
                                    flag = 1 << bit
                                    if physical_mask & flag and not next_mask & flag:
                                        earliest = max(earliest, pressed_at[bit] + .05)
                                    if next_mask & flag and not physical_mask & flag and bit in released_at:
                                        earliest = max(earliest, released_at[bit] + (0 if legacy else .01))
                                if earliest > now:
                                    self._condition.wait(min(.05, earliest - now))
                                    continue
                                if event.onset_keys and clock.position_us() - next_time > self.REBASE_LAG_US:
                                    clock.rebase(next_time)
                                seq += 1
                                sent = self.ctx.arduino.send_state(self._session, seq, next_mask)
                                written_at = time.monotonic()
                                for bit in range(len(KEYS)):
                                    flag = 1 << bit
                                    if next_mask & flag and not physical_mask & flag:
                                        pressed_at[bit] = written_at
                                    if physical_mask & flag and not next_mask & flag:
                                        released_at[bit] = written_at
                                physical_mask = next_mask
                            else:
                                sent = all(self.ctx.arduino.send(key, self.HOLD_MS, owner="music") for key in event.onset_keys)
                            if not sent:
                                raise RuntimeError("发送失败，请检查 Arduino 连接")
                            logical_mask = event.mask
                            suppressed_mask = next_suppressed
                        index += 1
                        continue
                with self._condition:
                    self._condition.wait(min(.05, clock.seconds_until(next_time)))
        finally:
            self._end_session()

    def _run(self) -> None:
        try:
            if not self.ctx.arduino.connect("AUTO", owner=self.id):
                raise RuntimeError("Arduino 连接失败，请检查设备与端口")
            caps = self.ctx.arduino.capabilities()
            modern = bool(caps.get("state") and caps.get("protocol", 1) >= 2)
            while True:
                with self._condition:
                    if self._stop_requested:
                        return
                    generation = self._generation
                    ident = self._requested
                    song = self.library.song(ident)
                    performance = self.library.performance(ident, int(caps.get("max_keys", 1)))
                    self._playing = ident
                    self._playing_name = song["name"]
                    self._position_us = 0
                    self._duration_us = performance.duration_us
                    self._speed = performance.settings["speed"]
                    self._phase = "countdown"
                    self._changed()
                if not self._count_in(generation):
                    continue
                completed = self._perform(performance, generation, modern, song["format"] == "txt")
                with self._condition:
                    if self._stop_requested:
                        return
                    if not completed or generation != self._generation:
                        continue
                    self._position_us = performance.duration_us
                    target = self._next(ident, 1, automatic=True)
                    if target is None:
                        self._finishing = True
                        self._phase = "finished"
                        self._changed("播放结束")
                        return
                    self._selected = target
                    self._requested = target
                    self._save_state()
        except Exception as exc:
            with self._condition:
                self._finishing = True
                if not self._stop_requested:
                    self._phase = "error"
                    self._error = {"code": "playback_failed", "message": str(exc)}
                    self._changed(str(exc))
        finally:
            self._end_session()
            self.ctx.arduino.release("music")
            with self._condition:
                self._paused = False
                self._countdown = 0
                self._clock = None
                self._thread = None
                self._changed()
