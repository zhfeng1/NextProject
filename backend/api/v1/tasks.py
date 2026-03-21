from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.task_service import task_service

router = APIRouter()


@router.post("/tasks")
async def create_task(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await task_service.create_task(
        db=db,
        current_user=current_user,
        site_id=(payload.get("site_id") or "").strip(),
        task_type=(payload.get("task_type") or "").strip(),
        provider=(payload.get("provider") or "").strip(),
        payload_data=payload,
        enqueue=True,
    )
    return {
        "ok": True,
        "task_id": str(task.id),
        "status": str(getattr(task.status, "value", task.status)),
        "site_id": getattr(task, "site_id", ""),
        "task_type": getattr(task, "task_type", ""),
    }


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await task_service.get_task(db, task_id, current_user)
    return {"ok": True, "task": task_service.serialize_task(task)}


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(
    task_id: str,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    logs = await task_service.get_task_logs(db, task_id, current_user, after_id=after_id, limit=limit)
    next_after_id = logs[-1]["id"] if logs else after_id
    return {"ok": True, "logs": logs, "next_after_id": next_after_id}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await task_service.cancel_task(db, task_id, current_user)
    return {"ok": True, "task_id": str(task.id), "status": str(getattr(task.status, "value", task.status))}


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await task_service.delete_task(db, task_id, current_user)
    return {"ok": True, "task_id": task_id}
