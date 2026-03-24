from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.site_service import site_service

router = APIRouter()


@router.get("/sites")
async def list_sites(
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    sites = await site_service.list_sites(db, user=current_user)
    return {
        "ok": True,
        "sites": [site_service.serialize_site(site) for site in sites],
        "default_site_id": sites[0].site_id if sites else "",
    }


@router.post("/sites")
async def create_site(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.create_site(
        db,
        current_user=current_user,
        site_id=(payload.get("site_id") or "").strip() or None,
        name=(payload.get("name") or "").strip() or None,
        auto_start=bool(payload.get("auto_start", True)),
        git_url=(payload.get("git_url") or "").strip() or None,
        git_username=(payload.get("git_username") or "").strip() or None,
        git_password=(payload.get("git_password") or "").strip() or None,
        git_branch=(payload.get("git_branch") or "").strip() or None,
        start_command=(payload.get("start_command") or "").strip() or None,
    )
    return {"ok": True, "site": site_service.serialize_site(site)}


@router.get("/sites/{site_id}")
async def get_site(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.get_site_by_public_id(db, site_id, current_user)
    data = site_service.load_site_data(site.site_id)
    return {"ok": True, "site": site_service.serialize_site(site), "data": data}


@router.post("/sites/{site_id}/start")
async def start_site(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.start_site(db, site_id, current_user)
    return {"ok": True, "site": site_service.serialize_site(site)}


@router.post("/sites/{site_id}/stop")
async def stop_site(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.stop_site(db, site_id, current_user)
    return {"ok": True, "site": site_service.serialize_site(site)}


@router.get("/sites/{site_id}/files")
async def list_site_files(
    site_id: str,
    path: str = Query(default=""),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.get_site_by_public_id(db, site_id, current_user)
    data = site_service.list_site_files(site.site_id, path)
    return {"ok": True, **data}


@router.get("/sites/{site_id}/file")
async def get_site_file(
    site_id: str,
    path: str = Query(default=""),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.get_site_by_public_id(db, site_id, current_user)
    data = site_service.read_site_file(site.site_id, path)
    return {"ok": True, **data}


@router.delete("/sites/{site_id}")
async def delete_site(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await site_service.delete_site(db, site_id, current_user)
    sites = await site_service.list_sites(db, user=current_user)
    return {
        "ok": True,
        "sites": [site_service.serialize_site(site) for site in sites],
        "default_site_id": sites[0].site_id if sites else "",
    }
