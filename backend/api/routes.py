"""REST API 路由。"""

import os
import threading
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend import state
from backend.core.arduino import DeviceBusyError
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
        "owner": state.arduino.current_owner(),
        "capabilities": state.arduino.capabilities(),
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
    # Invalidate workers before closing their persistent connection.
    for feature in state.features.values():
        if feature.requires_arduino:
            feature.stop()
    state.arduino.disconnect(force=True)
    state.bus.publish_status("Arduino 已断开")
    return {"ok": True}


@router.post("/key")
def send_key(payload: KeyPayload):
    hold_ms = payload.hold_ms if payload.hold_ms is not None else 50
    ok = state.arduino.press_key(payload.key, hold_ms)
    _check_manual_result(ok)
    return {"ok": ok}


@router.post("/mouse")
def send_mouse(payload: MousePayload):
    ok = state.arduino.send(payload.button)
    _check_manual_result(ok)
    return {"ok": ok}


def _check_manual_result(ok: bool) -> None:
    if not ok:
        owner = state.arduino.current_owner()
        if owner and owner != "manual":
            raise HTTPException(409, "设备正在被其他功能使用，请先停止该功能")
        raise HTTPException(503, state.arduino.last_error or "Arduino 未连接或按键发送失败")


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
    state.config.update(feature_id, payload.config)
    return {"ok": True}


@router.post("/features/{feature_id}/start")
def start_feature(feature_id: str):
    f = _get_feature(feature_id)
    cfg = {**f.default_config(), **state.config.get(feature_id)}
    try:
        f.start(cfg)
    except DeviceBusyError as exc:
        raise HTTPException(409, str(exc))
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


# ── 区域框选 ──────────────────────────────────────
@router.post("/region/select")
def select_region_endpoint():
    from loco_box.region_selector import select_region

    if any(f.blocks_region_selection and f.is_running() for f in state.features.values()):
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
