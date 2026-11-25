"""Local API for the independent pet viewer."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend import state

router = APIRouter(prefix="/api/pet-viewer", tags=["pet-viewer"])


class PetSelection(BaseModel):
    pet_id: int


def _viewer():
    feature = state.features.get("pet_viewer")
    if feature is None:
        raise HTTPException(404, "精灵查看功能未加载")
    return feature


@router.get("/state")
def viewer_state():
    return _viewer().state()


@router.get("/adapters")
def viewer_adapters():
    return _viewer().adapters()


@router.post("/demo")
def viewer_demo():
    try:
        return _viewer().demo()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/select")
def viewer_select(selection: PetSelection):
    try:
        return _viewer().select(selection.pet_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/history")
def viewer_history(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    try:
        return _viewer().history(limit, offset)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
