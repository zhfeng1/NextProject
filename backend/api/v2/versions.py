from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.version_service import version_service

router = APIRouter(prefix="/versions")


@router.get("/sites/{site_id}")
async def list_versions(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    versions = await version_service.list_versions(db, site_id, current_user)
    return {"ok": True, "versions": [version_service.serialize_version(item) for item in versions]}


@router.post("/sites/{site_id}/snapshot")
async def create_snapshot(
    site_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    version = await version_service.create_snapshot(
        db=db,
        site_id=site_id,
        commit_message=(payload.get("commit_message") or "").strip() or "Manual snapshot",
        created_by=str(getattr(current_user, "id")),
        current_user=current_user,
    )
    return {"ok": True, "version": version_service.serialize_version(version)}


@router.post("/sites/{site_id}/rollback")
async def rollback(
    site_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    version_number = int(payload.get("version_number") or 0)
    version = await version_service.rollback_to_version(db, site_id, version_number, current_user)
    return {"ok": True, "version": version_service.serialize_version(version)}
