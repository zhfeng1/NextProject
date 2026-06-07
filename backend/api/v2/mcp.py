from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.mcp_service import mcp_service

router = APIRouter(prefix="/mcp")


@router.get("/services")
async def list_mcp_services(
    project_id: str | None = Query(default=None),
    site_id: str | None = Query(default=None),
    scope_type: str | None = Query(default=None),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {
        "ok": True,
        "services": await mcp_service.list_services(
            db,
            current_user,
            project_id=project_id,
            site_id=site_id,
            scope_type=scope_type,
        ),
    }


@router.put("/services/{service_id}")
async def update_mcp_service(
    service_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = await mcp_service.update_service(db, current_user, service_id, payload)
    return {"ok": True, "service": service}


@router.post("/services/{service_id}/test")
async def test_mcp_service(
    service_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await mcp_service.test_service(db, current_user, service_id, payload)
