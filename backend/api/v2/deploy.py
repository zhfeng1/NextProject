from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.deploy_service import deploy_service

router = APIRouter(prefix="/deploy")


@router.post("/sites/{site_id}")
async def deploy_site(
    site_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    target = (payload.get("target") or "local").strip().lower()
    task = await deploy_service.create_deploy_task(db, site_id, current_user, target=target, options=payload)
    return {"ok": True, "task_id": str(task.id), "task_type": getattr(task, "task_type", "")}
