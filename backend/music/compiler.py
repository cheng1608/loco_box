"""Map every source onset through the converter's handpan rules and play it."""

import math
from collections import defaultdict
from typing import Any, Dict, Optional

from loco_box.handpan import detect_key, map_pitch_to_note, map_pitch_nearest, map_pitch_smooth
from backend.music.models import (
    DEFAULT_SETTINGS, HOLD_US, KEYS, RELEASE_GAP_US,
    ParsedSong, Performance, PerformanceEvent,
)


def normalize_settings(values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if values is not None and not isinstance(values, dict):
        raise ValueError("演奏设置必须是对象")
    result = dict(DEFAULT_SETTINGS)
    if values:
        unknown = set(values) - set(result)
        if unknown:
            raise ValueError("未知演奏设置：%s" % ", ".join(sorted(unknown)))
        result.update(values)
    tracks = result["selected_tracks"]
    if tracks is not None and (not isinstance(tracks, list) or any(type(t) is not int or t < 0 for t in tracks)):
        raise ValueError("selected_tracks 必须是音轨编号列表或 null")
    if tracks is not None:
        result["selected_tracks"] = sorted(set(tracks))
    if type(result["transpose"]) is not int or not -36 <= result["transpose"] <= 36:
        raise ValueError("移调范围为 -36 到 36 个半音")
    if result["range_policy"] in ("octave", "strict"):
        result["range_policy"] = "degree"
    if result["range_policy"] not in ("degree", "nearest", "smooth"):
        raise ValueError("未知音高映射策略")
    if result["root"] is not None and (type(result["root"]) is not int or not 0 <= result["root"] <= 11):
        raise ValueError("主调必须为自动或 0 到 11")
    if result["conflict_policy"] not in ("adapt", "strict", "skip"):
        raise ValueError("未知节奏处理策略")
    result["conflict_policy"] = "adapt"
    result["mapping_version"] = 2
    try:
        speed = float(result["speed"])
    except (TypeError, ValueError) as exc:
        raise ValueError("播放速度必须是数字") from exc
    if not math.isfinite(speed) or not .25 <= speed <= 2:
        raise ValueError("播放速度范围为 0.25 到 2 倍")
    result["speed"] = speed
    if type(result["skip_leading_silence"]) is not bool:
        raise ValueError("skip_leading_silence 必须为布尔值")
    return result


def compile_song(song: ParsedSong, values: Optional[Dict[str, Any]] = None, max_keys: int = 9) -> Performance:
    settings = normalize_settings(values)
    selected = settings["selected_tracks"]
    warnings = list(song.warnings)
    source = [note for note in song.notes if note.channel != 9 and (selected is None or note.track in selected)]
    if not source and song.notes:
        source = [note for note in song.notes if note.channel != 9] or list(song.notes)
        warnings.append("所选音轨没有可用音符，已自动使用文件中的可用音符继续演奏")
    source.sort(key=lambda note: (note.start_us, -note.pitch, note.track))
    # The old converter estimates the key from each chord's highest note.
    # Use that same histogram, while retaining ALL notes for performance.
    groups = []
    for note in source:
        if not groups or note.start_us - groups[-1][0] > 1000:
            groups.append((note.start_us, []))
        groups[-1][1].append(note)
    root = settings["root"]
    if root is None:
        root = detect_key([max(notes, key=lambda note: note.pitch).pitch for _, notes in groups])
    mapper = {"degree": map_pitch_to_note, "nearest": map_pitch_nearest, "smooth": map_pitch_smooth}[settings["range_policy"]]
    offset = groups[0][0] if groups and settings["skip_leading_silence"] else 0
    speed = settings["speed"]
    limit = max(1, min(len(KEYS), int(max_keys or 1)))
    gap = 0 if song.format == "txt" else RELEASE_GAP_US
    last_start: Dict[str, int] = {}
    ends: Dict[str, int] = {}
    pulses = []
    chord_count = max_active = retriggers = capacity = repeated = retimed = 0
    shift = 0
    nominal = previous_source = 0
    for group_index, (start_us, notes) in enumerate(groups):
        if group_index == 0:
            nominal = round((start_us - offset) / speed / 1000) * 1000
        else:
            # Same per-interval millisecond rounding as the TXT converter.
            nominal += round((start_us - previous_source) / speed / 1000) * 1000
        previous_source = start_us
        pending = [note.key or mapper(note.pitch + settings["transpose"], root) for note in notes]
        repeated += len(pending) - len(set(pending))
        # Same-key mappings and chords wider than the device are played in
        # successive batches. Every source note gets an actual key-down.
        while pending:
            batch = []
            rest = []
            for key in pending:
                if key not in batch and len(batch) < limit:
                    batch.append(key)
                else:
                    rest.append(key)
            pending = rest
            desired = nominal + shift
            onset = desired
            for key in batch:
                if key in last_start:
                    earliest = last_start[key] + HOLD_US + gap
                    if desired < earliest:
                        retriggers += 1
                    onset = max(onset, earliest)
            active = {key for key, end in ends.items() if end > onset}
            if len(active | set(batch)) > limit:
                capacity += len(batch)
            while len(active | set(batch)) > limit:
                onset = min(end for end in ends.values() if end > onset)
                active = {key for key, end in ends.items() if end > onset}
            shift += onset - desired
            if onset > nominal:
                retimed += len(batch)
            for key in batch:
                last_start[key] = onset
                ends[key] = onset + HOLD_US
                pulses.append((onset, key))
            max_active = max(max_active, len(active | set(batch)))
            if len(batch) > 1:
                chord_count += 1
    changes = defaultdict(lambda: {"on": [], "off": []})
    for onset, key in pulses:
        changes[onset]["on"].append(key)
        changes[onset + HOLD_US]["off"].append(key)
    events = []
    held = set()
    for time_us, change in sorted(changes.items()):
        released = held.intersection(change["off"])
        held.difference_update(change["off"])
        if released.intersection(change["on"]):
            events.append(PerformanceEvent(time_us, sum(1 << KEYS.index(key) for key in held)))
        held.update(change["on"])
        events.append(PerformanceEvent(time_us, sum(1 << KEYS.index(key) for key in held), tuple(change["on"])))
    duration = events[-1].time_us if events else 0
    if song.format == "txt":
        duration = max(round(song.duration_us / speed) + shift, duration)
    if repeated:
        warnings.append("%s 个同刻音符映射到同键，已分次敲击保留" % repeated)
    if retriggers or capacity:
        warnings.append("密集重击和超容量和弦已顺延演奏，保留全部音符")
    names = ("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")
    analysis = {
        "source_notes": len(source), "playable_notes": len(pulses), "chord_count": chord_count,
        "max_keys": max_active, "unmapped_notes": 0, "merged_notes": 0,
        "retrigger_conflicts": retriggers, "skipped_notes": 0, "capacity_conflicts": capacity,
        "repeated_mappings": repeated, "retimed_notes": retimed,
        "detected_root": root, "root_name": names[root],
        "warnings": warnings, "can_play": bool(pulses),
        "duration_ms": round(duration / 1000),
    }
    return Performance(tuple(events), duration, analysis, settings)
