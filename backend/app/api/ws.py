"""WebSocket 端点:把行情网关的 tick / bar 推送给前端。

网关在无 vnpy 时用本地模拟器产生数据,保证实时链路在开发期可联调。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.gateway_service import gateway

ws_router = APIRouter()


@ws_router.websocket("/ws/market")
async def market_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

    def on_message(message: dict[str, Any]) -> None:
        # 网关回调在后台线程,转投到事件循环安全入队。
        try:
            loop.call_soon_threadsafe(queue.put_nowait, message)
        except (asyncio.QueueFull, RuntimeError):
            pass

    gateway.add_listener(on_message)
    try:
        await websocket.send_json({"type": "hello", "status": gateway.status()})
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        gateway.remove_listener(on_message)
