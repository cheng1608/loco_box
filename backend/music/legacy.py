"""Compatibility adapter for existing key + pause TXT scores."""

import re
from typing import List, Tuple

from backend.music.models import HOLD_US, KEYS, PITCHES, ParsedSong, SourceNote


def parse_score(text: str) -> List[Tuple[str, int]]:
    notes = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        match = re.match(r"^\s*([A-Za-z])(?![A-Za-z0-9])(?:\s*[:=, ]\s*(\d+))?", line)
        if match and match.group(1).upper() in KEYS:
            notes.append((match.group(1).upper(), int(match.group(2) or 0)))
    return notes


def parse_legacy(data: bytes) -> ParsedSong:
    try:
        score = parse_score(data.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ValueError("旧谱文件必须使用 UTF-8 编码") from exc
    notes = []
    onset = 0
    for key, pause in score:
        notes.append(SourceNote(onset, onset + HOLD_US, PITCHES[KEYS.index(key)], 64, 0, 0, key))
        onset += HOLD_US + pause * 1000
    return ParsedSong("txt", tuple(notes), ({
        "id": 0, "name": "旧按键谱", "channels": [1], "note_count": len(notes),
        "pitch_min": None, "pitch_max": None, "percussion": False,
    },), onset)
