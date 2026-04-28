from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.mcp_service import mcp_service

router = APIRouter(prefix="/mcp")


@router.get("/services")
async def list_mcp_services(
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"ok": True, "services": await mcp_service.list_services(db, current_user)}


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
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await mcp_service.test_service(db, current_user, service_id)
