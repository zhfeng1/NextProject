from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.requirement_service import requirement_service

router = APIRouter(prefix="/sites")

@router.get("/{site_id}/requirements/latest")
async def get_latest_requirement(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    snapshot = await requirement_service.get_latest_snapshot(db, site_id)
    if not snapshot:
        return {"ok": True, "snapshot": None}
    return {
        "ok": True,
        "snapshot": requirement_service.serialize_snapshot(snapshot)
    }

@router.get("/{site_id}/requirements/events")
async def get_unprocessed_events(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    events = await requirement_service.get_unprocessed_events(db, site_id)
    return {
        "ok": True,
        "events": [requirement_service.serialize_event(e) for e in events]
    }
