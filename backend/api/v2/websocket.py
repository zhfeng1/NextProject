from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services.websocket_service import websocket_manager

router = APIRouter()


@router.websocket("/ws/tasks/{task_id}/logs")
async def task_logs_websocket(websocket: WebSocket, task_id: str) -> None:
    await websocket_manager.connect(task_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(task_id, websocket)
