"""Immutable musical source and game-performance data."""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

KEYS = ("B", "F", "G", "H", "J", "K", "T", "Y", "U")
PITCHES = (57, 64, 65, 67, 69, 71, 72, 74, 76)
HOLD_US = 50_000
RELEASE_GAP_US = 10_000
DEFAULT_SETTINGS = {
    "selected_tracks": None,
    "transpose": 0,
    "range_policy": "degree",
    "root": None,
    "conflict_policy": "adapt",
    "mapping_version": 2,
    "speed": 1.0,
    "skip_leading_silence": True,
}


@dataclass(frozen=True)
class SourceNote:
    start_us: int
    end_us: int
    pitch: int
    velocity: int
    track: int
    channel: int
    key: Optional[str] = None


@dataclass(frozen=True)
class ControlChange:
    time_us: int
    track: int
    channel: int
    control: int
    value: int


@dataclass(frozen=True)
class ParsedSong:
    format: str
    notes: Tuple[SourceNote, ...]
    tracks: Tuple[Dict[str, Any], ...]
    duration_us: int
    warnings: Tuple[str, ...] = ()
    controls: Tuple[ControlChange, ...] = ()


@dataclass(frozen=True)
class PerformanceEvent:
    time_us: int
    mask: int
    onset_keys: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Performance:
    events: Tuple[PerformanceEvent, ...]
    duration_us: int
    analysis: Dict[str, Any]
    settings: Dict[str, Any]
