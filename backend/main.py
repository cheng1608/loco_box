"""FastAPI 后端入口。

开发运行:
    .venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8790
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import state
from backend.api import routes, ws
from backend.core.preview import start_preview_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.bus.set_loop(asyncio.get_running_loop())
    preview = start_preview_loop(state.bus)
    app.state.ready = True
    try:
        yield
    finally:
        app.state.ready = False
        await asyncio.to_thread(preview.stop)
        for feature in state.features.values():
            try:
                await asyncio.to_thread(feature.stop)
            except Exception:
                logger.exception("Failed to stop feature %s", feature.id)
        await asyncio.to_thread(state.arduino.disconnect)
        state.bus.set_loop(None)


app = FastAPI(title="loco_box backend", lifespan=lifespan)

# 开发期放开跨域，便于 Vite 前端（不同端口）访问；打包后仍保持 127.0.0.1 单机。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router)
app.include_router(ws.router)
