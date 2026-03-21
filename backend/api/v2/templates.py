from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.template_service import template_service

router = APIRouter(prefix="/templates")


@router.get("")
async def list_templates(
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    templates = await template_service.list_templates(db, category=category, search=search, limit=limit)
    return {"ok": True, "templates": [template_service.serialize_template(item) for item in templates]}


@router.post("/sites/from-template")
async def create_site_from_template(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await template_service.create_site_from_template(
        db,
        template_id=(payload.get("template_id") or "").strip(),
        site_name=(payload.get("site_name") or "").strip(),
        current_user=current_user,
    )
    return {"ok": True, "site_id": site.site_id}
