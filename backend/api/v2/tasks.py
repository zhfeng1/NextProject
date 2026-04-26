from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db, require_role
from backend.services.task_service import task_service

router = APIRouter(prefix="/tasks")


@router.post("")
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
    return {"ok": True, "task_id": str(task.id), "task": task_service.serialize_task(task)}


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    response: Response,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    task = await task_service.get_task(db, task_id, current_user)
    return {"ok": True, "task": task_service.serialize_task(task)}


@router.get("/{task_id}/logs")
async def get_task_logs(
    task_id: str,
    response: Response,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    logs = await task_service.get_task_logs(db, task_id, current_user, after_id=after_id, limit=limit)
    next_after_id = logs[-1]["id"] if logs else after_id
    return {"ok": True, "logs": logs, "next_after_id": next_after_id}


@router.get("/{task_id}/provider-output")
async def get_task_provider_output(
    task_id: str,
    response: Response,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    data = await task_service.get_task_provider_output(db, task_id, current_user)
    return {"ok": True, **data}


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    current_user: object = Depends(require_role("developer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await task_service.cancel_task(db, task_id, current_user)
    return {"ok": True, "task": task_service.serialize_task(task)}


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    current_user: object = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await task_service.delete_task(db, task_id, current_user)
    return {"ok": True, "task_id": task_id}


@router.get("/site/{site_id}")
async def list_site_tasks(
    site_id: str,
    limit: int = Query(default=30, ge=1, le=200),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tasks = await task_service.list_site_tasks(db, site_id, current_user, limit=limit)
    return {"ok": True, "site_id": site_id, "tasks": [task_service.serialize_task(task) for task in tasks]}
