"""自动演奏：解析按键谱 → Arduino 按键序列（音乐播放器式歌单 + 播放控件）。

乐谱直接写 9 音手碟的键位字母：B/F/G/H/J/K/T/Y/U（不再经音名转换）。
每个音固定按住 HOLD_MS 毫秒，谱面给出每个音之后的停顿毫秒数。

面板展示 data/scores/ 下所有 .txt 作为歌单；悬浮窗提供
上一曲 / 暂停·播放 / 下一曲 / 播放模式 四个控件。

播放模式五态：
    sequential  列表播放  播完当前自动下一首，列表播完停（默认）
    single      单曲播放  只播当前这首，播完停，不自动切下一首
    repeat_one  单曲循环  一直循环当前这首
    repeat_all  列表循环  按歌单顺序循环整张列表
    shuffle     随机播放  播完随机挑下一首

手动「下一曲」始终生效（顺序 +1，shuffle 时随机）；「上一曲」始终列表 -1。
"""

import random
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.core.config import SCORES_DIR
from backend.features import Feature, FeatureContext, register
from loco_box.serial_bridge import SerialBridge


@register
class MusicFeature(Feature):
    id = "music"
    name = "自动演奏"
    config_schema = [
        {"key": "mode", "label": "播放模式", "type": "select", "default": "sequential"},
        {"key": "current", "label": "当前曲目", "type": "text", "default": ""},
    ]

    MODES = ("sequential", "single", "repeat_one", "repeat_all", "shuffle")
    MODE_NAMES = {
        "sequential": "列表播放",
        "single": "单曲播放",
        "repeat_one": "单曲循环",
        "repeat_all": "列表循环",
        "shuffle": "随机播放",
    }

    HOLD_MS = 50
    COUNTDOWN_SECS = 3

    # 9 音手碟对应的键位字母（乐谱直接写这些字母）
    VALID_KEYS = frozenset("BFGHJKTUY")

    def __init__(self, ctx: FeatureContext) -> None:
        super().__init__(ctx)
        self._active = False
        self._paused = False
        self._mode = "sequential"
        self._current = ""
        self._playlist: List[str] = []
        self._thread: threading.Thread = None  # type: ignore[assignment]
        self._stop_event = threading.Event()
        self._next_event = threading.Event()
        self._prev_event = threading.Event()

    # ── 状态读取 ──────────────────────────────────
    def is_running(self) -> bool:
        return self._active

    def is_paused(self) -> bool:
        return self._paused

    def current_song(self) -> str:
        return self._current

    def mode(self) -> str:
        return self._mode

    def playlist(self) -> List[str]:
        return self._load_playlist()

    # ── 按键谱解析 ──────────────────────────────────
    @classmethod
    def parse_score(cls, text: str) -> List[Tuple[str, int]]:
        """解析按键谱文本，返回 [(按键, 停顿ms), ...]。

        每行一个音：`按键 停顿ms`（按键 = B/F/G/H/J/K/T/Y/U 之一，
        分隔可用空格/逗号/冒号/等号，停顿可省略=0）。
        空行、`#` 注释行、非法按键直接跳过。
        """
        notes: List[Tuple[str, int]] = []
        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "#" in line:
                line = line.split("#", 1)[0].strip()
            if not line:
                continue
            m = re.match(r"^\s*([A-Za-z])(?![A-Za-z0-9])(?:\s*[:=, ]\s*(\d+))?", line)
            if not m:
                continue
            key = m.group(1).upper()
            if key not in cls.VALID_KEYS:
                continue
            pause = int(m.group(2)) if m.group(2) else 0
            notes.append((key, pause))
        return notes

    # ── 歌单 / 文件 ────────────────────────────────
    def _load_playlist(self) -> List[str]:
        try:
            SCORES_DIR.mkdir(parents=True, exist_ok=True)
            return sorted(
                p.name for p in SCORES_DIR.iterdir()
                if p.is_file() and p.suffix.lower() == ".txt"
            )
        except OSError:
            return []

    def _load_notes(self, name: str) -> List[Tuple[str, int]]:
        if not name:
            return []
        path = SCORES_DIR / name
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        return self.parse_score(text)

    # ── 控制方法 ──────────────────────────────────
    def start(self, config: Dict[str, Any]) -> None:
        self._playlist = self._load_playlist()
        if not self._playlist:
            raise ValueError("歌单为空，请先在 data/scores/ 放入按键谱文件")

        mode = str(config.get("mode") or "sequential")
        self._mode = mode if mode in self.MODES else "sequential"

        cur = str(config.get("current") or "")
        self._current = cur if cur in self._playlist else self._playlist[0]
        self._save_state()

        old = self._thread
        if self._active and old and old.is_alive():
            self._active = False
            self._stop_event.set()
            old.join(timeout=1.0)

        self._paused = False
        self._stop_event.clear()
        self._next_event.clear()
        self._prev_event.clear()
        self._active = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._active = False
        self._paused = False
        self._stop_event.set()
        self.ctx.bus.publish_status("已停止")

    def pause(self) -> None:
        if not self._active or self._paused:
            return
        self._paused = True
        # 「已暂停」由 _loop 在下一个音符边界发布

    def resume(self) -> None:
        if not self._active or not self._paused:
            return
        self._paused = False
        self.ctx.bus.publish_status("继续演奏")

    def select_song(self, name: str) -> bool:
        if name not in self._load_playlist():
            return False
        self._current = name
        self._save_state()
        return True

    def set_mode(self, mode: str) -> bool:
        if mode not in self.MODES:
            return False
        self._mode = mode
        self._save_state()
        self.ctx.bus.publish_status(f"播放模式：{self.MODE_NAMES[mode]}")
        return True

    def next_track(self) -> None:
        self._advance_manual(1)
        if self._active:
            self._next_event.set()

    def prev_track(self) -> None:
        self._advance_manual(-1)
        if self._active:
            self._prev_event.set()

    # ── 内部辅助 ──────────────────────────────────
    def _save_state(self) -> None:
        self.ctx.config.set("music", {"mode": self._mode, "current": self._current})

    def _random_song(self, pl: List[str]) -> str:
        if len(pl) <= 1:
            return pl[0]
        others = [s for s in pl if s != self._current]
        return random.choice(others) if others else self._current

    def _advance_manual(self, direction: int) -> None:
        """手动上一曲/下一曲：改 _current；shuffle 时「下一曲」随机。"""
        pl = self._load_playlist()
        if not pl:
            return
        if self._mode == "shuffle" and direction > 0:
            self._current = self._random_song(pl)
        else:
            try:
                idx = pl.index(self._current)
            except ValueError:
                idx = 0
            self._current = pl[(idx + direction) % len(pl)]
        self._save_state()
        self.ctx.bus.publish_status(f"切到：{self._current}")

    def _advance_after_song(self) -> Optional[str]:
        """当前曲自然播完时按模式决定下一首；返回 None 表示停止。"""
        pl = self._load_playlist()
        if not pl:
            return None
        try:
            idx = pl.index(self._current)
        except ValueError:
            idx = 0
        if self._mode == "repeat_one":
            return self._current
        if self._mode == "single":
            return None
        if self._mode == "repeat_all":
            return pl[(idx + 1) % len(pl)]
        if self._mode == "shuffle":
            return self._random_song(pl)
        # sequential：列表播完停
        return pl[idx + 1] if idx + 1 < len(pl) else None

    # ── 演奏线程 ──────────────────────────────────
    def _loop(self) -> None:
        # 首次（未连接 Arduino）后台连接；与第一首歌的倒计时并行
        connect_thread: Optional[threading.Thread] = None
        connect_result: Dict[str, Any] = {}
        if not self.ctx.arduino.is_connected():
            def _run_connect() -> None:
                com = SerialBridge.find_arduino() or self.ctx.config.get_global("com_port", "AUTO")
                if not com:
                    connect_result["ok"] = False
                    return
                connect_result["ok"] = self.ctx.arduino.connect(com)

            connect_thread = threading.Thread(target=_run_connect, daemon=True)
            connect_thread.start()

        # 播放循环：每首歌开始前倒计时 COUNTDOWN_SECS 秒
        while self._active:
            for i in range(self.COUNTDOWN_SECS, 0, -1):
                self.ctx.bus.publish_status(f"准备开始 · {i}")
                if self._stop_event.wait(1.0):
                    self._active = False
                    return

            # 连接结果只在第一次倒计时结束后检查一次
            if connect_thread is not None:
                connect_thread.join(timeout=5.0)
                if not connect_result.get("ok"):
                    self.ctx.bus.publish_status("Arduino 连接失败")
                    self._active = False
                    return
                connect_thread = None
            notes = self._load_notes(self._current)
            if not notes:
                nxt = self._advance_after_song()
                if nxt is None:
                    self._active = False
                    self.ctx.bus.publish_status("播放结束")
                    return
                self._current = nxt
                self._save_state()
                continue

            total = len(notes)
            song_name = self._current
            for idx, (key, pause_ms) in enumerate(notes):
                # 暂停：在音符边界等待续播/停止
                if self._paused:
                    self.ctx.bus.publish_status("已暂停")
                    while self._paused and self._active:
                        time.sleep(0.1)
                    if not self._active:
                        return
                    self.ctx.bus.publish_status("继续演奏")
                if not self._active:
                    return
                # 手动上一曲/下一曲：打断当前曲，跳出后 while 重读已更新的 _current
                if self._next_event.is_set():
                    self._next_event.clear()
                    break
                if self._prev_event.is_set():
                    self._prev_event.clear()
                    break
                self.ctx.bus.publish_status(f"演奏中 · {song_name} · 第 {idx + 1}/{total} 音")
                if not self.ctx.arduino.send(key, self.HOLD_MS):
                    self.ctx.bus.publish_status("发送失败，请检查 Arduino 连接")
                    self._active = False
                    return
                # send() 立即返回，按住 HOLD_MS 在 Arduino 端异步完成，与这里的等待重叠。
                # 谱面「停顿」是「按住之后」的间隔（转谱已扣掉 HOLD_MS），故须补回 HOLD_MS，
                # 否则每个音起点固定提前 50ms，音符越密偏差占比越大（快歌抢拍）。
                # 效果：起点间隔 = max(HOLD_MS, 原曲间隔)，不会突破按住时长的物理下限。
                if self._stop_event.wait((self.HOLD_MS + pause_ms) / 1000.0):
                    return
            else:
                # 当前曲自然播完（未被 break）
                nxt = self._advance_after_song()
                if nxt is None:
                    self._active = False
                    self.ctx.bus.publish_status("播放结束")
                    return
                self._current = nxt
                self._save_state()
