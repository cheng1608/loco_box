"""WebSocket 端点：转发事件总线消息（实时预览帧 / 截图 / 状态 / 事件）。"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend import state

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, preview: bool = False):
    await ws.accept()
    q = state.bus.subscribe(preview=preview)

    async def send_events():
        while True:
            event = await q.get()
            await ws.send_json(event)

    async def wait_for_disconnect():
        # Receiving is necessary even for an outgoing-only feed: otherwise an
        # idle socket can disconnect without ever releasing its subscription.
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return

    tasks = [asyncio.create_task(send_events()), asyncio.create_task(wait_for_disconnect())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    finally:
        state.bus.unsubscribe(q)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
