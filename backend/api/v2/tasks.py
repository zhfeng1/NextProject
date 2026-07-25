from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db, require_role
from backend.core.task_stream_ticket import (
    TaskStreamTicketStoreUnavailable,
    task_stream_ticket_store,
)
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


@router.get("")
async def list_board_tasks(
    project_id: str | None = Query(default=None),
    repo_id: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    board_status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tasks = await task_service.list_board_tasks(
        db,
        current_user,
        project_id=project_id,
        repo_id=repo_id,
        provider=provider,
        board_status=board_status,
        priority=priority,
        keyword=keyword,
        limit=limit,
    )
    return {"ok": True, "tasks": tasks}


@router.get("/site/{site_id}")
async def list_site_tasks(
    site_id: str,
    task_type: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tasks = await task_service.list_site_tasks(
        db, site_id, current_user, limit=limit, task_type=task_type
    )
    return {"ok": True, "site_id": site_id, "tasks": [task_service.serialize_task(task) for task in tasks]}


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
    return {"ok": True, "task": await task_service.serialize_task_detail(db, task)}


@router.patch("/{task_id}/board-status")
async def update_board_status(
    task_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await task_service.update_board_status(
        db,
        task_id,
        current_user,
        str(payload.get("board_status") or ""),
    )
    return {"ok": True, "task": await task_service.serialize_task_detail(db, task)}


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


@router.post("/{task_id}/ws-ticket")
async def create_task_stream_ticket(
    task_id: str,
    response: Response,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    task = await task_service.get_task(db, task_id, current_user)
    try:
        ticket = await task_stream_ticket_store.issue(
            user_id=str(getattr(current_user, "id", "")),
            task_id=str(task.id),
            ttl_seconds=60,
        )
    except TaskStreamTicketStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail="Task stream authentication is unavailable") from exc
    return {"ok": True, "task_id": str(task.id), "ticket": ticket, "expires_in": 60}


@router.get("/{task_id}/execution-details")
async def get_task_execution_details(
    task_id: str,
    response: Response,
    after_log_id: int = Query(default=0, ge=0),
    after_trace_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=200),
    current_user: object = Depends(require_role("developer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    data = await task_service.get_task_execution_details(
        db,
        task_id,
        current_user,
        after_log_id=after_log_id,
        after_trace_seq=after_trace_seq,
        limit=limit,
    )
    return {"ok": True, **data}


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    current_user: object = Depends(require_role("developer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await task_service.cancel_task(db, task_id, current_user)
    return {"ok": True, "task": task_service.serialize_task(task)}


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str,
    current_user: object = Depends(require_role("developer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await task_service.retry_task(db, task_id, current_user)
    return {"ok": True, "task": await task_service.serialize_task_detail(db, task)}


@router.post("/{task_id}/rollback")
async def rollback_task(
    task_id: str,
    current_user: object = Depends(require_role("developer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await task_service.rollback_task(db, task_id, current_user)
    return {"ok": True, "task": await task_service.serialize_task_detail(db, task)}


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    current_user: object = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await task_service.delete_task(db, task_id, current_user)
    return {"ok": True, "task_id": task_id}
