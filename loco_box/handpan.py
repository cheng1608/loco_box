"""Shared handpan mapping used by MIDI conversion and direct playback."""

from typing import List

# Historical note labels used by the score converter and local simulator.
NOTE_TO_KEY = {
    "L6": "B", "M3": "F", "M4": "G", "M5": "H",
    "M6": "J", "M7": "K", "H1": "T", "H2": "Y", "H3": "U",
}

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

def circular_dist(a: int, b: int) -> int:
    """pitch class 环形半音距离（0..6）。"""
    d = abs(a - b) % 12
    return d if d <= 6 else 12 - d


def detect_key(pitches: List[int]) -> int:
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


def transpose_to_c(pitch: int, root: int) -> int:
    """把 root 大调里的音高折到最近的 C 大调音级，返回对应音高（保留大致八度）。"""
    pc = pitch % 12
    best_degree = min(range(7), key=lambda d: circular_dist(pc, (root + MAJOR[d]) % 12))
    result = (pitch // 12) * 12 + MAJOR[best_degree]
    while result - pitch > 6:
        result -= 12
    while pitch - result > 6:
        result += 12
    return result


def map_pitch_to_note(pitch: int, root: int) -> str:
    """把一个 MIDI 音高映射到手碟 9 音之一（转调到 C 大调 + 量化掉临时升降音）。"""
    pc = pitch % 12
    best_name, best_score = "T", float("inf")
    for degree in range(7):
        scale_pc = (root + MAJOR[degree]) % 12
        semitone = circular_dist(pc, scale_pc)

        # 该音级下手碟上离原音最近的目标
        name, target = min(DEGREE_TARGETS[degree], key=lambda nt: abs(nt[1] - pitch))

        # 音级正确优先（*1000 保证主导），绝对音高距离只用来破升降号平局
        score = semitone * 1000 + abs(target - pitch)
        if score < best_score:
            best_name, best_score = name, score
    return best_name


def map_pitch_nearest(pitch: int, root: int) -> str:
    """就近映射：先转调到 C 大调，再取手碟上绝对音高最近的音（牺牲音准换连贯）。

    与 degree 一样先按主调折到 C 大调，再做纯就近；手碟缺中音 1/2 时，
    do/re 会就近落到 L6/M3 等相邻音，旋律更连贯但音级可能改变。
    """
    p_c = transpose_to_c(pitch, root)
    return min(ALL_NOTES, key=lambda nt: abs(nt[1] - p_c))[0]


def map_pitch_smooth(pitch: int, root: int) -> str:
    """平滑映射：先转调到 C 大调，再就近落到手碟音；只接受全音(≤2 半音)
    内的就近，超过就回退到音级折叠（保音准，接受跳八度）。

    相比 degree：re(D4) 就近到 mi(M3)，不再跳八度到 H2；
    相比 nearest：do(C4) 不会落到 la(L6)——小三度太远，仍走 H1。
    """
    p_c = transpose_to_c(pitch, root)
    name, target = min(ALL_NOTES, key=lambda nt: abs(nt[1] - p_c))
    if abs(target - p_c) <= 2:
        return name
    return map_pitch_to_note(pitch, root)
