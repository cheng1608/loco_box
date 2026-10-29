"""REST API 路由。"""

import os
import threading
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend import state
from backend.core.config import SCORES_DIR
from loco_box.serial_bridge import SerialBridge

router = APIRouter(prefix="/api")


class KeyPayload(BaseModel):
    key: str
    hold_ms: Optional[int] = None


class MousePayload(BaseModel):
    button: str = "MOUSE_LEFT"


class ConnectPayload(BaseModel):
    port: str = "AUTO"


class ConfigPayload(BaseModel):
    config: Dict[str, Any]


class ParsePayload(BaseModel):
    score: str = ""


class SelectPayload(BaseModel):
    name: str


class ModePayload(BaseModel):
    mode: str


# ── 基础 ──────────────────────────────────────────
@router.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "service": "loco_box",
        "ready": getattr(request.app.state, "ready", False),
        "protocol": 1,
        "pid": os.getpid(),
    }


@router.get("/status")
def status():
    return {
        "arduino_connected": state.arduino.is_connected(),
        "port": state.arduino.port(),
    }


@router.get("/ports")
def list_ports():
    return {"ports": SerialBridge.list_ports()}


# ── Arduino ───────────────────────────────────────
@router.post("/arduino/connect")
def connect_arduino(payload: ConnectPayload):
    ok = state.arduino.connect(payload.port)
    if ok:
        state.bus.publish_status(f"Arduino 已就绪 · {state.arduino.port()}")
    else:
        state.bus.publish_status("Arduino 连接失败")
    return {"ok": ok, "port": state.arduino.port()}


@router.post("/arduino/disconnect")
def disconnect_arduino():
    state.arduino.disconnect()
    state.bus.publish_status("Arduino 已断开")
    return {"ok": True}


@router.post("/key")
def send_key(payload: KeyPayload):
    hold_ms = payload.hold_ms if payload.hold_ms is not None else 50
    ok = state.arduino.press_key(payload.key, hold_ms)
    return {"ok": ok}


@router.post("/mouse")
def send_mouse(payload: MousePayload):
    ok = state.arduino.send(payload.button)
    return {"ok": ok}


# ── 功能 ──────────────────────────────────────────
def _get_feature(feature_id: str):
    f = state.features.get(feature_id)
    if f is None:
        raise HTTPException(404, "功能不存在")
    return f


@router.get("/features")
def list_features():
    return {
        "features": [
            {"id": fid, "name": f.name, "running": f.is_running()}
            for fid, f in state.features.items()
        ]
    }


@router.get("/features/{feature_id}/config")
def get_feature_config(feature_id: str):
    f = _get_feature(feature_id)
    merged = {**f.default_config(), **state.config.get(feature_id)}
    return {"config": merged}


@router.put("/features/{feature_id}/config")
def set_feature_config(feature_id: str, payload: ConfigPayload):
    _get_feature(feature_id)
    state.config.set(feature_id, payload.config)
    return {"ok": True}


@router.post("/features/{feature_id}/start")
def start_feature(feature_id: str):
    f = _get_feature(feature_id)
    cfg = {**f.default_config(), **state.config.get(feature_id)}
    try:
        f.start(cfg)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "running": f.is_running()}


@router.post("/features/{feature_id}/stop")
def stop_feature(feature_id: str):
    f = _get_feature(feature_id)
    f.stop()
    return {"ok": True}


@router.post("/features/box_monitor/template")
def capture_box_template():
    f = state.features.get("box_monitor")
    if f is None:
        raise HTTPException(404, "功能不存在")
    try:
        return f.capture_template()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ── 自动演奏（简谱文件） ──────────────────────────
@router.get("/music/scores")
def list_music_scores():
    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    names = sorted(
        p.name for p in SCORES_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == ".txt"
    )
    return {"scores": names}


@router.get("/music/scores/{name}")
def read_music_score(name: str):
    safe = os.path.basename(name)
    if not safe or safe != name or not safe.lower().endswith(".txt"):
        raise HTTPException(404, "文件不存在")
    path = SCORES_DIR / safe
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(500, str(exc))
    return {"name": safe, "content": content}


@router.post("/music/open_folder")
def open_music_scores_folder():
    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(SCORES_DIR))  # type: ignore[attr-defined]
    except OSError as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True}


@router.post("/music/parse")
def parse_music_score(payload: ParsePayload):
    f = state.features.get("music")
    if f is None:
        raise HTTPException(404, "功能不存在")
    notes = f.parse_score(payload.score)
    return {
        "count": len(notes),
        "notes": [{"key": k, "pause": p} for k, p in notes],
    }


def _get_music():
    f = state.features.get("music")
    if f is None:
        raise HTTPException(404, "功能不存在")
    return f


@router.get("/music/state")
def music_state():
    f = _get_music()
    return {
        "playlist": f.playlist(),
        "current": f.current_song(),
        "mode": f.mode(),
        "running": f.is_running(),
        "paused": f.is_paused(),
    }


@router.post("/music/select")
def music_select(payload: SelectPayload):
    f = _get_music()
    ok = f.select_song(payload.name)
    return {"ok": ok}


@router.post("/music/next")
def music_next():
    f = _get_music()
    f.next_track()
    return {"ok": True}


@router.post("/music/prev")
def music_prev():
    f = _get_music()
    f.prev_track()
    return {"ok": True}


@router.post("/music/mode")
def music_mode(payload: ModePayload):
    f = _get_music()
    ok = f.set_mode(payload.mode)
    if not ok:
        raise HTTPException(400, f"未知播放模式：{payload.mode}")
    return {"ok": True}


@router.post("/music/pause")
def music_pause():
    f = _get_music()
    f.pause()
    return {"ok": True}


@router.post("/music/resume")
def music_resume():
    f = _get_music()
    f.resume()
    return {"ok": True}


# ── 区域框选 ──────────────────────────────────────
@router.post("/region/select")
def select_region_endpoint():
    from loco_box.region_selector import select_region

    if any(f.is_running() for f in state.features.values()):
        raise HTTPException(409, "请先停止当前运行的功能再框选")

    result: Dict[str, Any] = {}
    done = threading.Event()

    def on_selected(region: Dict[str, int]) -> None:
        result["region"] = region
        done.set()

    def on_cancel() -> None:
        result["cancelled"] = True
        done.set()

    select_region(on_selected, on_cancel)
    done.wait()
    if result.get("cancelled"):
        return {"ok": False, "cancelled": True}
    return {"ok": True, "region": result["region"]}
