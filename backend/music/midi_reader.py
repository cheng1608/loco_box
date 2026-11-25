"""Read original MIDI without discarding chords or changing tempo."""

from collections import defaultdict, deque
from io import BytesIO
from typing import Any, Dict, List, Tuple

from backend.music.models import ControlChange, ParsedSong, SourceNote

MAX_MESSAGES = 500_000


def parse_midi(data: bytes) -> ParsedSong:
    try:
        import mido  # optional until a MIDI is actually imported/read
    except ImportError as exc:
        raise ValueError("缺少 MIDI 解析依赖 mido，请运行 .venv/Scripts/python.exe -m pip install -r requirements.txt") from exc

    try:
        midi = mido.MidiFile(file=BytesIO(data))
    except (OSError, EOFError, ValueError, TypeError) as exc:
        raise ValueError("无法解析 MIDI 文件：%s" % exc) from exc
    if midi.type not in (0, 1):
        raise ValueError("暂不支持 MIDI type 2 独立轨道，请另存为 type 0 或 type 1")
    if midi.ticks_per_beat <= 0:
        raise ValueError("暂不支持 SMPTE 时间分辨率，请转换为 PPQ MIDI")

    events: List[Tuple[int, int, int, Any]] = []
    tracks: List[Dict[str, Any]] = []
    for track_id, track in enumerate(midi.tracks):
        tick = 0
        pitches: List[int] = []
        channels = set()
        name = "音轨 %s" % (track_id + 1)
        for order, message in enumerate(track):
            tick += message.time
            if tick < 0:
                raise ValueError("MIDI 包含无效的负时间")
            events.append((tick, track_id, order, message))
            if len(events) > MAX_MESSAGES:
                raise ValueError("MIDI 事件过多（上限 500000），请先拆分曲目")
            if message.type == "track_name" and message.name.strip():
                name = message.name.strip()
            if message.type == "note_on" and message.velocity > 0:
                pitches.append(message.note)
                channels.add(message.channel)
        tracks.append({
            "id": track_id, "name": name, "channels": sorted(c + 1 for c in channels),
            "note_count": len(pitches), "pitch_min": min(pitches) if pitches else None,
            "pitch_max": max(pitches) if pitches else None,
            "percussion": bool(channels) and channels == {9},
        })

    # Stable source ordering resolves coincident tempo messages. Never sort by
    # tempo value: a real tick-zero tempo must override the implicit default.
    events.sort(key=lambda event: event[:3])
    numerator = 0
    previous_tick = 0
    tempo = 500_000
    active = defaultdict(deque)
    notes: List[SourceNote] = []
    unmatched = 0
    sustain = 0
    expressive = 0
    controls = []
    now_us = 0
    for tick, track_id, _, message in events:
        numerator += (tick - previous_tick) * tempo
        previous_tick = tick
        now_us = numerator // midi.ticks_per_beat
        if message.type == "set_tempo":
            if message.tempo <= 0:
                raise ValueError("MIDI 速度必须大于零")
            tempo = message.tempo
        elif message.type == "note_on" and message.velocity > 0:
            active[(track_id, message.channel, message.note)].append((now_us, message.velocity))
        elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            key = (track_id, message.channel, message.note)
            if active[key]:
                start, velocity = active[key].popleft()
                notes.append(SourceNote(start, now_us, message.note, velocity, track_id, message.channel))
            else:
                unmatched += 1
        elif message.type == "control_change":
            controls.append(ControlChange(now_us, track_id, message.channel, message.control, message.value))
            if message.control == 64:
                sustain += 1
        elif message.type in ("pitchwheel", "aftertouch", "polytouch"):
            expressive += 1
    for (track_id, channel, pitch), starts in active.items():
        for start, velocity in starts:
            notes.append(SourceNote(start, max(start, now_us), pitch, velocity, track_id, channel))
            unmatched += 1
    warnings = []
    if unmatched:
        warnings.append("存在 %s 个未配对音符事件，已保留可识别的起音" % unmatched)
    if sustain:
        warnings.append("包含延音踏板；手碟按起音短击，踏板不改变按键时长")
    if expressive:
        warnings.append("包含弯音或触后；游戏固定键位无法还原这些表达")
    notes.sort(key=lambda note: (note.start_us, note.track, note.channel, note.pitch))
    return ParsedSong("midi", tuple(notes), tuple(tracks), now_us, tuple(warnings), tuple(controls))
