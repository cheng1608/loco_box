"""MIDI → 洛克王国 9 音手碟按键谱转换工具（命令行 + 可作库导入）。

命令行用法::

    python scripts/midi2score.py 歌曲.mid                        # 单文件
    python scripts/midi2score.py 歌曲.mid -o data/scores/歌曲.txt
    python scripts/midi2score.py --dir 歌曲目录                  # 批量：目录下所有 .mid
    python scripts/midi2score.py --dir 歌曲目录 --recursive --out-dir data/scores
    python scripts/midi2score.py 歌曲.mid --polyphony top --root auto --hold-ms 50

依赖::

    pip install mido

库接口（后续做进后端时直接复用这些函数）::

    from scripts.midi2score import convert_midi_to_score, convert_directory, score_to_text

    notes = convert_midi_to_score("song.mid", root=None, polyphony="top")   # 单曲 -> [(按键, 停顿ms)]
    text  = score_to_text(notes, song_name="song")
    wrote = convert_directory("midi_dir", out_dir="data/scores")            # 批量 -> [Path]

算法要点（详见 docs/MUSIC.md）::

    MIDI ─tempo换算→ 音符起点(ms) ─和弦折叠→ 单音序列 ─音级折叠→ 9 音 ─间隔-HOLD→ 停顿
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import mido
except ImportError:  # pragma: no cover - 环境未装 mido 时给出友好提示
    mido = None  # type: ignore

# ── 手碟 9 音常量 ──────────────────────────────────────────────
# 大调音阶各音级（do re mi fa sol la si）的半音偏移
MAJOR = (0, 2, 4, 5, 7, 9, 11)

# 每个音级在手碟上可用的目标 (键位, MIDI 音高)。
# 键位必须是 music.py 的 parse_score 能识别的 9 键之一：B/F/G/H/J/K/T/Y/U
DEGREE_TARGETS = {
    0: [("T", 72)],              # do   -> 高音1
    1: [("Y", 74)],              # re   -> 高音2
    2: [("F", 64), ("U", 76)],   # mi   -> 中音3 / 高音3
    3: [("G", 65)],              # fa   -> 中音4
    4: [("H", 67)],              # sol  -> 中音5
    5: [("B", 57), ("J", 69)],   # la   -> 低音6 / 中音6
    6: [("K", 71)],              # si   -> 中音7
}

# 手碟 9 音完整 (键位, MIDI 音高)，按音高升序 —— 就近映射策略用
ALL_NOTES = [
    ("B", 57), ("F", 64), ("G", 65), ("H", 67),
    ("J", 69), ("K", 71), ("T", 72), ("Y", 74), ("U", 76),
]

# GM 打击乐通道 = 通道 10（0 基下标 9），手碟无打击音，默认跳过
GM_PERCUSSION_CHANNEL = 9


# ── MIDI 解析：tick → 毫秒 ─────────────────────────────────────
def _build_tempo_map(mid: "mido.MidiFile") -> List[Tuple[int, int]]:
    """收集所有 set_tempo 事件，返回按绝对 tick 排序的 [(tick, usec_per_beat)]。"""
    tempos = [(0, 500000)]  # 默认 120 BPM
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "set_tempo":
                tempos.append((abs_tick, msg.tempo))
    tempos.sort()
    return tempos


def _tick_to_ms(tick: int, ticks_per_beat: int, tempos: List[Tuple[int, int]]) -> float:
    """按速度表分段累加，把绝对 tick 换算成毫秒。"""
    us = 0.0
    prev_tick, prev_us = tempos[0]
    for cur_tick, cur_us in tempos[1:]:
        if cur_tick >= tick:
            break
        us += (cur_tick - prev_tick) * prev_us
        prev_tick, prev_us = cur_tick, cur_us
    us += (tick - prev_tick) * prev_us
    return us / ticks_per_beat / 1000.0


MELODY_NAME_HINTS = ("melody", "lead", "vocal", "solo", "main", "主旋律", "旋律", "人声")
PERCUSSION_HINTS = ("drum", "percussion", "sfx", "fx", "鼓", "打击")


def _track_name(track) -> str:
    return " ".join(m.name for m in track if m.type == "track_name").lower()


def _resolve_auto_track(mid: "mido.MidiFile"):
    """auto 模式：优先按音轨名找旋律轨；找不到就取非鼓轨里音符最多的一条。"""
    # 1) 名字匹配旋律关键词
    for t in mid.tracks:
        if any(h in _track_name(t) for h in MELODY_NAME_HINTS):
            return t
    # 2) 兜底：非鼓轨（跳过 channel 9 与打击乐名）里 note_on 最多的一条
    best, best_count = None, -1
    for t in mid.tracks:
        if any(h in _track_name(t) for h in PERCUSSION_HINTS):
            continue
        count = sum(1 for m in t if m.type == "note_on" and m.velocity > 0 and m.channel != 9)
        if count > best_count:
            best, best_count = t, count
    return best


def _select_tracks(mid: "mido.MidiFile", track: Optional[str]):
    """按 track 筛选轨道：auto=自动找旋律轨；纯数字=索引(0 起)；否则按音轨名匹配。"""
    if not track:
        return mid.tracks
    if track.lower() == "auto":
        t = _resolve_auto_track(mid)
        if t is None:
            raise ValueError("auto 未找到可用的旋律轨")
        return [t]
    if track.isdigit():
        idx = int(track)
        if 0 <= idx < len(mid.tracks):
            return [mid.tracks[idx]]
        raise ValueError(f"轨道索引越界: {idx}（共 {len(mid.tracks)} 轨）")
    needle = track.lower()
    matched = [
        t for t in mid.tracks
        if any(m.type == "track_name" and needle in m.name.lower() for m in t)
    ]
    if not matched:
        raise ValueError(f"未找到名为 {track!r} 的轨道")
    return matched


def _midi_to_onsets(
    path: Path, track: Optional[str] = None
) -> List[Tuple[float, int, int, int]]:
    """提取所选轨道的 note_on(velocity>0)，返回 [(起点ms, 音高, 力度, 通道)]，按起点升序。"""
    mid = mido.MidiFile(str(path))
    tempos = _build_tempo_map(mid)  # 速度表用全部轨道（全局）
    ppq = mid.ticks_per_beat

    events: List[Tuple[float, int, int, int]] = []
    for track in _select_tracks(mid, track):
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                events.append(
                    (_tick_to_ms(abs_tick, ppq, tempos), msg.note, msg.velocity, msg.channel)
                )

    # 时间升序；同刻高音在前（和弦折叠取 top 时的稳定顺序）
    events.sort(key=lambda e: (e[0], -e[1]))
    return events


# ── 和弦折叠 ───────────────────────────────────────────────────
def _reduce_polyphony(
    events: List[Tuple[float, int, int, int]], eps: float = 1.0, policy: str = "top"
) -> List[Tuple[float, int, int, int]]:
    """把同一时刻（起点相差 <= eps 毫秒）的和弦折叠成单音。

    policy: top=最高音(默认，保旋律) / bottom=最低音 / loudest=力度最大
    """
    out: List[Tuple[float, int, int, int]] = []
    i, n = 0, len(events)
    while i < n:
        t0 = events[i][0]
        group: List[Tuple[float, int, int, int]] = []
        while i < n and events[i][0] - t0 <= eps:
            group.append(events[i])
            i += 1
        if policy == "bottom":
            chosen = min(group, key=lambda e: e[1])
        elif policy == "loudest":
            chosen = max(group, key=lambda e: e[2])
        else:  # top
            chosen = max(group, key=lambda e: e[1])
        out.append(chosen)
    return out


# ── 音高归约：任意 MIDI 音 → 9 音名 ───────────────────────────
def _circular_dist(a: int, b: int) -> int:
    """pitch class 环形半音距离（0..6）。"""
    d = abs(a - b) % 12
    return d if d <= 6 else 12 - d


def _detect_key(pitches: List[int]) -> int:
    """用 pitch-class 直方图猜大调主音（0=C..11=B）。"""
    hist = [0] * 12
    for p in pitches:
        hist[p % 12] += 1
    best_root, best_score = 0, -1
    for root in range(12):
        score = sum(hist[(root + i) % 12] for i in MAJOR)
        if score > best_score:
            best_root, best_score = root, score
    return best_root


def _transpose_to_c(pitch: int, root: int) -> int:
    """把 root 大调里的音高折到最近的 C 大调音级，返回对应音高（保留大致八度）。"""
    pc = pitch % 12
    best_degree = min(range(7), key=lambda d: _circular_dist(pc, (root + MAJOR[d]) % 12))
    result = (pitch // 12) * 12 + MAJOR[best_degree]
    while result - pitch > 6:
        result -= 12
    while pitch - result > 6:
        result += 12
    return result


def _map_pitch_to_note(pitch: int, root: int) -> str:
    """把一个 MIDI 音高映射到手碟 9 音之一（转调到 C 大调 + 量化掉临时升降音）。"""
    pc = pitch % 12
    best_name, best_score = "T", float("inf")
    for degree in range(7):
        scale_pc = (root + MAJOR[degree]) % 12
        semitone = _circular_dist(pc, scale_pc)

        # 该音级下手碟上离原音最近的目标
        name, target = min(DEGREE_TARGETS[degree], key=lambda nt: abs(nt[1] - pitch))

        # 音级正确优先（*1000 保证主导），绝对音高距离只用来破升降号平局
        score = semitone * 1000 + abs(target - pitch)
        if score < best_score:
            best_name, best_score = name, score
    return best_name


def _map_pitch_nearest(pitch: int, root: int) -> str:
    """就近映射：先转调到 C 大调，再取手碟上绝对音高最近的音（牺牲音准换连贯）。

    与 degree 一样先按主调折到 C 大调，再做纯就近；手碟缺中音 1/2 时，
    do/re 会就近落到 L6/M3 等相邻音，旋律更连贯但音级可能改变。
    """
    p_c = _transpose_to_c(pitch, root)
    return min(ALL_NOTES, key=lambda nt: abs(nt[1] - p_c))[0]


def _map_pitch_smooth(pitch: int, root: int) -> str:
    """平滑映射：先转调到 C 大调，再就近落到手碟音；只接受全音(≤2 半音)
    内的就近，超过就回退到音级折叠（保音准，接受跳八度）。

    相比 degree：re(D4) 就近到 mi(M3)，不再跳八度到 H2；
    相比 nearest：do(C4) 不会落到 la(L6)——小三度太远，仍走 H1。
    """
    p_c = _transpose_to_c(pitch, root)
    name, target = min(ALL_NOTES, key=lambda nt: abs(nt[1] - p_c))
    if abs(target - p_c) <= 2:
        return name
    return _map_pitch_to_note(pitch, root)


# ── 主转换 + 文本输出（库接口）─────────────────────────────────
def convert_midi_to_score(
    midi_path: str,
    track: Optional[str] = None,
    root: Optional[int] = None,
    polyphony: str = "top",
    strategy: str = "degree",
    hold_ms: int = 50,
    velocity_threshold: int = 0,
    skip_percussion: bool = True,
    min_gap: int = 100,
    tail_pause: int = 0,
) -> List[Tuple[str, int]]:
    """把 MIDI 转成 [(按键, 停顿ms), ...]，可直接喂给 music.py 的 parse_score 语义。

    :param track: 只转换指定轨道。None=全部轨道；"auto"=自动找旋律轨；纯数字=轨道索引(0 起)；
                  否则按音轨名匹配。整编 MIDI（多乐器）建议 track="auto" 或 "MELODY"。
    :param root: 主音 pitch class。None=自动检测（转调到 C 大调）；0=不转调（只量化升降音）；
                 1..11=手动指定。
    :param polyphony: 和弦折叠策略 top/bottom/loudest。
    :param strategy: 音高映射策略 degree/nearest/smooth。degree=音级折叠（默认，保音准，
                     但手碟缺中音 1/2，do/re 会跳高八度到 H1/H2）；nearest=纯就近映射
                     （保连贯，但 do 会落到 L6 差小三度）；smooth=平滑映射
                     （就近但只接受全音≤2 半音，超了就回退音级）。
    :param hold_ms: 每个音的固定按住时长，计算停顿时扣掉（与 music.py 的 HOLD_MS 一致）。
    :param velocity_threshold: 力度低于此值的音当幽灵音丢弃（0=保留全部）。
    :param skip_percussion: 跳过 GM 打击乐通道（channel 9）。
    :param min_gap: 相邻起点小于此毫秒的音丢弃（默认 100=丢间隔<100ms 的贴脸音，避免过密）。
    :param tail_pause: 最后一个音之后的停顿。
    """
    if mido is None:
        raise RuntimeError("缺少 mido 库，请先执行 pip install mido")
    if strategy not in ("degree", "nearest", "smooth"):
        raise ValueError(f"未知映射策略: {strategy!r}（可选 degree / nearest / smooth）")

    events = _midi_to_onsets(Path(midi_path), track=track)

    if skip_percussion:
        events = [e for e in events if e[3] != GM_PERCUSSION_CHANNEL]
    if velocity_threshold > 0:
        events = [e for e in events if e[2] >= velocity_threshold]

    events = _reduce_polyphony(events, policy=polyphony)
    if not events:
        return []

    pitches = [e[1] for e in events]
    key = _detect_key(pitches) if root is None else root

    if min_gap > 0:
        kept = [events[0]]
        for e in events[1:]:
            if e[0] - kept[-1][0] >= min_gap:
                kept.append(e)
        events = kept

    notes: List[Tuple[str, int]] = []
    last = len(events) - 1
    for i, (t, pitch, _vel, _ch) in enumerate(events):
        if strategy == "degree":
            name = _map_pitch_to_note(pitch, key)
        elif strategy == "nearest":
            name = _map_pitch_nearest(pitch, key)
        else:  # smooth
            name = _map_pitch_smooth(pitch, key)
        if i == last:
            pause = tail_pause
        else:
            # 起点间隔 - 按住时长 = 停顿；贴太近则钳到 0（实际会拉长成 hold_ms）
            pause = max(0, round(events[i + 1][0] - t) - hold_ms)
        notes.append((name, pause))
    return notes


def score_to_text(notes: List[Tuple[str, int]], song_name: str = "") -> str:
    """把 [(按键, 停顿ms)] 格式化成 music.py 的 parse_score 能读的 .txt 文本。"""
    header = [f"# {song_name}" if song_name else "# 未命名"]
    header.append("# 由 MIDI 自动转换")
    body = [f"{note} {pause}" for note, pause in notes]
    return "\n".join(header + body) + "\n"


def convert_directory(
    dir_path: str,
    out_dir: Optional[str] = None,
    recursive: bool = False,
    **convert_kwargs,
) -> List[Path]:
    """批量转换目录下所有 .mid，返回已写入的 .txt 路径列表。

    :param out_dir: 输出目录。None=写到各自 .mid 旁边；给定则全部平铺到该目录（同名会覆盖）。
    :param recursive: 是否递归子目录。
    其余关键字参数透传给 convert_midi_to_score。
    单个文件损坏/无音符会跳过并打印警告，不中断整批。
    """
    if mido is None:
        raise RuntimeError("缺少 mido 库，请先执行 pip install mido")

    root = Path(dir_path)
    if not root.is_dir():
        raise ValueError(f"不是目录: {dir_path}")

    pattern = "**/*.mid" if recursive else "*.mid"
    written: List[Path] = []
    for mid in sorted(root.glob(pattern)):
        try:
            notes = convert_midi_to_score(str(mid), **convert_kwargs)
        except Exception as exc:  # 单个文件损坏不中断整批
            print(f"跳过 {mid}: {exc}", file=sys.stderr)
            continue
        if not notes:
            print(f"跳过 {mid}: 未提取到音符", file=sys.stderr)
            continue

        if out_dir:
            out = Path(out_dir) / (mid.stem + ".txt")
            out.parent.mkdir(parents=True, exist_ok=True)
        else:
            out = mid.with_suffix(".txt")
        out.write_text(score_to_text(notes, song_name=mid.stem), encoding="utf-8")
        written.append(out)
    return written


# ── 命令行入口 ─────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="MIDI → 洛克王国 9 音手碟简谱转换",
        epilog="输出格式：每行「按键 停顿ms」，与 data/scores/*.txt 一致，可直接放进去演奏。",
    )
    parser.add_argument("midi", nargs="?", help="输入 .mid 文件路径（单文件模式）")
    parser.add_argument("-o", "--output", help="单文件模式输出 .txt 路径；默认与输入同目录同名 .txt")
    parser.add_argument("--dir", dest="directory", help="批量模式：转换目录下所有 .mid")
    parser.add_argument("--out-dir", help="批量模式输出目录；默认每个 .txt 写到各自 .mid 旁边")
    parser.add_argument("--recursive", action="store_true", help="批量模式递归子目录")
    parser.add_argument(
        "--track",
        help="只转换指定轨道：auto=自动找旋律轨；纯数字=轨道索引(0 起)；否则按音轨名匹配（如 --track MELODY）",
    )
    parser.add_argument(
        "--root",
        choices=["auto", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
        default="auto",
        help="主音：auto=自动检测并转调到 C 大调（默认）；0=不转调只量化升降音；1..11 手动指定",
    )
    parser.add_argument(
        "--polyphony", choices=["top", "bottom", "loudest"], default="top",
        help="和弦折叠策略（默认 top=保最高音/旋律）",
    )
    parser.add_argument(
        "--strategy", choices=["degree", "nearest", "smooth"], default="degree",
        help="音高映射策略：degree=音级折叠（默认，保音准）；nearest=纯就近（保连贯）；smooth=平滑（就近限全音≤2 半音）",
    )
    parser.add_argument("--hold-ms", type=int, default=50, help="每个音固定按住毫秒（默认 50）")
    parser.add_argument("--min-gap", type=int, default=100, help="丢弃起点间隔小于此毫秒的贴脸音（默认 100）")
    parser.add_argument("--velocity-threshold", type=int, default=0, help="力度低于此值的音丢弃（默认 0）")
    parser.add_argument("--tail-pause", type=int, default=0, help="最后一个音之后的停顿毫秒（默认 0）")
    parser.add_argument("--keep-percussion", action="store_true", help="保留打击乐轨（默认跳过）")
    args = parser.parse_args(argv)

    if not args.midi and not args.directory:
        parser.error("请提供输入 .mid 文件，或用 --dir 指定目录批量转换")

    root = None if args.root == "auto" else int(args.root)
    kwargs = dict(
        track=args.track,
        root=root,
        polyphony=args.polyphony,
        strategy=args.strategy,
        hold_ms=args.hold_ms,
        velocity_threshold=args.velocity_threshold,
        skip_percussion=not args.keep_percussion,
        min_gap=args.min_gap,
        tail_pause=args.tail_pause,
    )

    try:
        if args.directory:
            written = convert_directory(
                args.directory, out_dir=args.out_dir, recursive=args.recursive, **kwargs
            )
            print(f"批量完成：共转换 {len(written)} 首")
            return 0
        notes = convert_midi_to_score(args.midi, **kwargs)
    except (RuntimeError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if not notes:
        print("未提取到音符，输出为空", file=sys.stderr)
        return 0

    out = Path(args.output) if args.output else Path(args.midi).with_suffix(".txt")
    out.write_text(score_to_text(notes, song_name=Path(args.midi).stem), encoding="utf-8")
    print(f"已生成 {len(notes)} 个音 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
