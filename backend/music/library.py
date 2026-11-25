"""Original-file music library, persistent per-song settings and parse caches."""

import hashlib
import copy
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.music.compiler import compile_song, normalize_settings
from backend.music.legacy import parse_legacy
from backend.music.models import ParsedSong, Performance

MAX_FILE_BYTES = 16 * 1024 * 1024


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(temporary), str(path))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


class MusicLibrary:
    def __init__(self, root: Path, legacy_dir: Path):
        self.root = root
        self.legacy_dir = legacy_dir
        self._lock = threading.RLock()
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._parsed: Dict[str, ParsedSong] = {}
        self._compiled: Dict[Any, Performance] = {}
        self._settings: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        index = self.root / "index.json"
        if index.exists():
            try:
                data = json.loads(index.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("songs"), list):
                    raise ValueError("Invalid index")
                for item in data["songs"]:
                    ident = item.get("id", "")
                    if (isinstance(ident, str) and len(ident) == 64
                            and all(c in "0123456789abcdef" for c in ident)
                            and item.get("extension") in (".mid", ".midi", ".txt")
                            and not item.get("legacy")
                            and isinstance(item.get("name"), str)
                            and isinstance(item.get("filename"), str)):
                        self._entries[ident] = item
                    else:
                        raise ValueError("Invalid song entry")
            except (OSError, ValueError, TypeError, AttributeError):
                # Preserve an unreadable index for diagnosis; don't overwrite it.
                raise ValueError("曲库索引无法读取，请备份并检查 data/music/index.json")
        self._loaded = True

    @staticmethod
    def _parse(data: bytes, suffix: str) -> ParsedSong:
        if suffix in (".mid", ".midi"):
            from backend.music.midi_reader import parse_midi
            return parse_midi(data)
        if suffix == ".txt":
            return parse_legacy(data)
        raise ValueError("请选择 .mid、.midi 或旧版 .txt 谱面")

    @staticmethod
    def _summary(ident: str, filename: str, parsed: ParsedSong, legacy: bool = False) -> Dict[str, Any]:
        return {
            "id": ident, "name": Path(filename).stem, "filename": filename,
            "format": parsed.format, "duration_ms": round(parsed.duration_us / 1000),
            "note_count": len(parsed.notes), "track_count": len(parsed.tracks), "legacy": legacy,
        }

    def _path(self, item: Dict[str, Any]) -> Path:
        if item.get("legacy"):
            return self.legacy_dir / item["filename"]
        return self.root / "originals" / (item["id"] + item["extension"])

    def refresh(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._load()
            found = set()
            if self.legacy_dir.exists():
                for path in sorted(self.legacy_dir.glob("*.txt")):
                    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                        continue
                    ident = "legacy-" + hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:24]
                    found.add(ident)
                    signature = (path.stat().st_mtime_ns, path.stat().st_size)
                    existing = self._entries.get(ident)
                    if existing and existing.get("signature") == signature:
                        continue
                    try:
                        parsed = parse_legacy(path.read_bytes())
                    except (OSError, ValueError):
                        continue
                    item = self._summary(ident, path.name, parsed, True)
                    item["signature"] = signature
                    self._entries[ident] = item
                    self._parsed[ident] = parsed
                    self._invalidate(ident)
            for ident in list(self._entries):
                if self._entries[ident].get("legacy") and ident not in found:
                    self._entries.pop(ident)
                    self._parsed.pop(ident, None)
                    self._invalidate(ident)
            return self.summaries()

    def summaries(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._load()
            return [self._public(item) for item in sorted(self._entries.values(), key=lambda s: (s["name"].lower(), s["id"]))]

    @staticmethod
    def _public(item: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in item.items() if k not in ("signature", "extension")}

    def import_file(self, filename: str, data: bytes) -> Dict[str, Any]:
        if not data or len(data) > MAX_FILE_BYTES:
            raise ValueError("文件为空或超过 16 MB 限制")
        # A browser filename is a display name, never an arbitrary disk path.
        filename = filename.replace("\\", "/").split("/")[-1].strip()
        if not filename or len(filename) > 240:
            raise ValueError("无效文件名")
        suffix = Path(filename).suffix.lower()
        parsed = self._parse(data, suffix)
        if not parsed.notes:
            raise ValueError("文件没有可识别的音符")
        ident = hashlib.sha256(data).hexdigest()
        with self._lock:
            self._load()
            if ident in self._entries:
                return {"song": self._public(self._entries[ident]), "duplicate": True}
            originals = self.root / "originals"
            originals.mkdir(parents=True, exist_ok=True)
            path = originals / (ident + suffix)
            temporary = path.with_suffix(path.suffix + ".tmp")
            try:
                temporary.write_bytes(data)
                os.replace(str(temporary), str(path))
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            item = self._summary(ident, filename, parsed)
            item.update(extension=suffix, imported_at=datetime.now(timezone.utc).isoformat())
            # Commit the manifest before publishing an in-memory entry. A failed
            # disk write must remain retryable instead of becoming a false duplicate.
            pending = [s for s in self._entries.values() if not s.get("legacy")] + [item]
            _atomic_json(self.root / "index.json", {"songs": pending})
            self._entries[ident] = item
            self._parsed[ident] = parsed
            return {"song": self._public(item), "duplicate": False}

    def delete(self, ident: str) -> Dict[str, Any]:
        """Remove a library entry, keeping its local files together for recovery."""
        with self._lock:
            ident = self.resolve(ident)
            item = self._entries[ident]
            source = self._path(item)
            source_dir = self.legacy_dir if item.get("legacy") else self.root / "originals"
            if source.parent.resolve() != source_dir.resolve():
                raise ValueError("曲目文件位置无效，无法删除")
            settings = self.root / "settings" / (ident + ".json")
            trash = self.root / "trash" / uuid.uuid4().hex
            moves: List[Tuple[Path, Path]] = []
            try:
                _atomic_json(trash / "song.json", {
                    "song": self._public(item),
                    "deleted_at": datetime.now(timezone.utc).isoformat(),
                })
                for original, target in ((source, trash / ("original" + source.suffix)),
                                         (settings, trash / "settings.json")):
                    if original.exists():
                        os.replace(str(original), str(target))
                        moves.append((original, target))
                remaining = [entry for key, entry in self._entries.items()
                             if key != ident and not entry.get("legacy")]
                _atomic_json(self.root / "index.json", {"songs": remaining})
            except Exception:
                # A failed commit must leave both the visible library and its
                # source files available, so the user can retry the deletion.
                for original, target in reversed(moves):
                    os.replace(str(target), str(original))
                try:
                    (trash / "song.json").unlink(missing_ok=True)
                    trash.rmdir()
                except OSError:
                    pass
                raise
            self._entries.pop(ident)
            self._parsed.pop(ident, None)
            self._settings.pop(ident, None)
            self._invalidate(ident)
            return self._public(item)

    def resolve(self, ident_or_name: str) -> str:
        with self._lock:
            self._load()
            if ident_or_name in self._entries:
                return ident_or_name
            matches = [s["id"] for s in self._entries.values() if s["filename"] == ident_or_name]
            if len(matches) == 1:
                return matches[0]
            raise ValueError("曲目不存在，请刷新曲库")

    def song(self, ident: str) -> Dict[str, Any]:
        with self._lock:
            return self._public(self._entries[self.resolve(ident)])

    def parsed(self, ident: str) -> ParsedSong:
        with self._lock:
            ident = self.resolve(ident)
            if ident not in self._parsed:
                item = self._entries[ident]
                self._parsed[ident] = self._parse(self.original(ident), self._path(item).suffix.lower())
            return self._parsed[ident]

    def original(self, ident: str) -> bytes:
        with self._lock:
            ident = self.resolve(ident)
            path = self._path(self._entries[ident])
            if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("曲目原文件缺失或过大，请重新导入")
            return path.read_bytes()

    def settings(self, ident: str) -> Dict[str, Any]:
        with self._lock:
            ident = self.resolve(ident)
            if ident not in self._settings:
                path = self.root / "settings" / (ident + ".json")
                values = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
                if isinstance(values, dict) and values.get("mapping_version", 1) < 2:
                    # Existing imports adopt the corrected converter defaults;
                    # retain track selection, speed and other deliberate edits.
                    values = {**values, "range_policy": "degree", "root": None,
                              "conflict_policy": "adapt", "mapping_version": 2}
                self._settings[ident] = normalize_settings(values)
            return copy.deepcopy(self._settings[ident])

    def update_settings(self, ident: str, values: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            ident = self.resolve(ident)
            updated = normalize_settings({**self.settings(ident), **values})
            # Validate the track selection before writing persistent settings.
            compile_song(self.parsed(ident), updated)
            _atomic_json(self.root / "settings" / (ident + ".json"), updated)
            self._settings[ident] = updated
            self._invalidate(ident)
            return dict(updated)

    def _invalidate(self, ident: str) -> None:
        self._compiled = {key: value for key, value in self._compiled.items() if key[0] != ident}

    def performance(self, ident: str, max_keys: int = 9) -> Performance:
        with self._lock:
            ident = self.resolve(ident)
            key = (ident, max_keys)
            if key not in self._compiled:
                self._compiled[key] = compile_song(self.parsed(ident), self.settings(ident), max_keys)
            return self._compiled[key]

    def detail(self, ident: str, max_keys: int = 9) -> Dict[str, Any]:
        with self._lock:
            return {
                "song": self.song(ident), "tracks": list(self.parsed(ident).tracks),
                "settings": self.settings(ident), "analysis": dict(self.performance(ident, max_keys).analysis),
            }
