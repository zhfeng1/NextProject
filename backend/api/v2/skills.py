from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.skill_service import skill_service

router = APIRouter(prefix="/skills")


@router.get("")
async def list_skills(
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"ok": True, "skills": await skill_service.list_skills(db, current_user)}


@router.post("")
async def create_skill(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"ok": True, "skill": await skill_service.create_skill(db, current_user, payload)}


@router.put("/{skill_id}")
async def update_skill(
    skill_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"ok": True, "skill": await skill_service.update_skill(db, current_user, skill_id, payload)}


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await skill_service.delete_skill(db, current_user, skill_id)
    return {"ok": True, "skill_id": skill_id}


@router.post("/import")
async def import_skill(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"ok": True, "skill": await skill_service.import_skill(db, current_user, payload)}


@router.post("/{skill_id}/bind-site")
async def bind_skill_to_site(
    skill_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site_id = str(payload.get("site_id") or "").strip()
    bind = bool(payload.get("bind", True))
    skill = await skill_service.bind_site(db, current_user, skill_id, site_id, bind=bind)
    return {"ok": True, "skill": skill}


@router.get("/site/{site_id}")
async def list_site_bound_skills(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"ok": True, "skills": await skill_service.get_bound_skills(db, current_user, site_id)}
