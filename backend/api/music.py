"""Music library and playback API, separate from generic device routes."""

import asyncio
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel

from backend import state
from backend.features.music import MusicBusyError
from backend.music.library import MAX_FILE_BYTES

router = APIRouter(prefix="/api/music", tags=["music"])


class SongPayload(BaseModel):
    song_id: Optional[str] = None
    name: Optional[str] = None


class ModePayload(BaseModel):
    mode: str


class ParsePayload(BaseModel):
    score: str = ""


def _music():
    feature = state.features.get("music")
    if feature is None:
        raise HTTPException(404, "演奏功能未加载")
    return feature


def _song_id(value: str) -> str:
    feature = _music()
    feature.refresh_library()
    try:
        return feature.library.resolve(value)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/state")
def music_state():
    return _music().state()


@router.get("/library")
def music_library():
    return {"songs": _music().refresh_library()}


@router.post("/import")
async def import_music(request: Request, filename: str = Query(...)):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_FILE_BYTES:
        raise HTTPException(413, "文件超过 16 MB 限制")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_FILE_BYTES:
            raise HTTPException(413, "文件超过 16 MB 限制")
        data.extend(chunk)
    feature = _music()
    try:
        result = await asyncio.to_thread(feature.library.import_file, filename, bytes(data))
        await asyncio.to_thread(feature.refresh_library)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/songs/{song_id}")
def music_detail(song_id: str):
    ident = _song_id(song_id)
    try:
        return _music().detail(ident)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/songs/{song_id}/settings")
def music_settings(song_id: str):
    return music_detail(song_id)


@router.delete("/songs/{song_id}")
def delete_music(song_id: str):
    ident = _song_id(song_id)
    feature = _music()
    try:
        songs = feature.delete_song(ident)
        return {"ok": True, "song_id": ident, "songs": songs, "state": feature.state()}
    except MusicBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, "曲目删除失败，请检查文件占用或磁盘权限后重试") from exc


@router.put("/songs/{song_id}/settings")
def update_music_settings(song_id: str, values: Dict[str, Any] = Body(...)):
    ident = _song_id(song_id)
    feature = _music()
    try:
        feature.library.update_settings(ident, values)
        return feature.detail(ident)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/play")
def play_music(payload: Optional[SongPayload] = Body(None)):
    feature = _music()
    try:
        feature.play((payload.song_id or payload.name) if payload else None)
        return feature.state()
    except MusicBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/select")
def select_music(payload: SongPayload):
    feature = _music()
    if not feature.select_song(payload.song_id or payload.name or ""):
        raise HTTPException(404, "曲目不存在，请刷新曲库")
    return feature.state()


@router.post("/pause")
def pause_music():
    feature = _music()
    feature.pause()
    return feature.state()


@router.post("/resume")
def resume_music():
    feature = _music()
    feature.resume()
    return feature.state()


@router.post("/stop")
def stop_music():
    feature = _music()
    feature.stop()
    return feature.state()


@router.post("/next")
def next_music():
    feature = _music()
    try:
        feature.next_track()
    except MusicBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return feature.state()


@router.post("/prev")
def previous_music():
    feature = _music()
    try:
        feature.prev_track()
    except MusicBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return feature.state()


@router.post("/mode")
def set_music_mode(payload: ModePayload):
    feature = _music()
    if not feature.set_mode(payload.mode):
        raise HTTPException(400, "未知播放模式")
    return feature.state()


# Keep original TXT endpoints for existing local scripts and bookmarks.
@router.get("/scores")
def list_music_scores():
    return {"scores": [song["filename"] for song in _music().refresh_library() if song["format"] == "txt"]}


@router.get("/scores/{name}")
def read_music_score(name: str):
    ident = _song_id(name)
    feature = _music()
    song = feature.library.song(ident)
    if song["format"] != "txt":
        raise HTTPException(400, "MIDI 文件不提供文本谱面")
    return {"name": song["filename"], "content": feature.library.original(ident).decode("utf-8-sig")}


@router.post("/open_folder")
def open_music_folder():
    path = _music().library.legacy_dir
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except (OSError, AttributeError) as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"ok": True}


@router.post("/parse")
def parse_music_score(payload: ParsePayload):
    notes = _music().parse_score(payload.score)
    return {"count": len(notes), "notes": [{"key": key, "pause": pause} for key, pause in notes]}
