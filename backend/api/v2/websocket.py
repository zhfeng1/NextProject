from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.models import Task, TaskLog
from backend.services.websocket_service import websocket_manager

router = APIRouter()


@router.websocket("/ws/tasks/{task_id}/logs")
async def task_logs_websocket(
    websocket: WebSocket,
    task_id: str,
    after_id: int = Query(0, description="Only return logs after this ID"),
) -> None:
    await websocket_manager.connect(task_id, websocket)
    try:
        # 1. Send initial task status
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, task_id)
            if task:
                status_val = getattr(task.status, "value", task.status)
                await websocket.send_json({
                    "type": "status",
                    "status": status_val,
                    "task_id": task_id,
                })

                # 2. Replay history logs after after_id
                rows = await db.execute(
                    select(TaskLog)
                    .where(TaskLog.task_id == task_id, TaskLog.id > after_id)
                    .order_by(TaskLog.id.asc())
                    .limit(500)
                )
                for log_entry in rows.scalars().all():
                    await websocket.send_json({
                        "type": "log",
                        "data": {
                            "id": log_entry.id,
                            "level": log_entry.level,
                            "line": log_entry.line,
                            "ts": log_entry.ts.isoformat() if getattr(log_entry, "ts", None) else None,
                        },
                    })
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Task not found: {task_id}",
                })

        # 3. Send history_end marker
        await websocket.send_json({"type": "history_end"})

        # 4. Keep alive: heartbeat + listen for client messages
        async def heartbeat():
            while True:
                await asyncio.sleep(30)
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            while True:
                data = await websocket.receive_text()
                # Handle pong or other client messages
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "pong":
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass
        except WebSocketDisconnect:
            pass
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
    finally:
        websocket_manager.disconnect(task_id, websocket)
