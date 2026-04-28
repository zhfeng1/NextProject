from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db, require_role
from backend.services.site_service import site_service

router = APIRouter(prefix="/sites")


@router.get("")
async def list_sites(
    include_deleted: bool = Query(default=False),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    sites = await site_service.list_sites(db, user=current_user, include_deleted=include_deleted)
    return {"ok": True, "sites": [site_service.serialize_site(site) for site in sites]}


@router.post("")
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
        template_id=(payload.get("template_id") or "").strip() or None,
        auto_start=bool(payload.get("auto_start", False)),
        config=payload.get("config") or {},
        git_url=(payload.get("git_url") or "").strip() or None,
        git_username=(payload.get("git_username") or "").strip() or None,
        git_password=(payload.get("git_password") or "").strip() or None,
        git_branch=(payload.get("git_branch") or "").strip() or None,
        start_command=(payload.get("start_command") or "").strip() or None,
    )
    return {"ok": True, "site": site_service.serialize_site(site)}


@router.get("/{site_id}")
async def get_site(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.get_site_by_public_id(db, site_id, current_user)
    return {
        "ok": True,
        "site": site_service.serialize_site(site),
        "data": site_service.load_site_data(site.site_id),
    }


@router.post("/{site_id}/start")
async def start_site(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.start_site(db, site_id, current_user)
    return {"ok": True, "site": site_service.serialize_site(site)}


@router.post("/{site_id}/stop")
async def stop_site(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.stop_site(db, site_id, current_user)
    return {"ok": True, "site": site_service.serialize_site(site)}


@router.post("/{site_id}/adjust")
async def adjust_site(
    site_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    instruction = (payload.get("instruction") or "").strip()
    site = await site_service.apply_adjustment(db, site_id, current_user, instruction)
    return {"ok": True, "site_id": site.site_id, "preview_url": site_service.preview_url_for_site(site.site_id)}


@router.get("/{site_id}/files")
async def list_site_files(
    site_id: str,
    path: str = Query(default=""),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.get_site_by_public_id(db, site_id, current_user)
    data = site_service.list_site_files(site.site_id, path)
    return {"ok": True, **data}


@router.get("/{site_id}/file")
async def get_site_file(
    site_id: str,
    path: str = Query(default=""),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.get_site_by_public_id(db, site_id, current_user)
    data = site_service.read_site_file(site.site_id, path)
    return {"ok": True, **data}


@router.get("/{site_id}/requirements")
async def get_requirements(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.get_site_by_public_id(db, site_id, current_user)
    req_file: Path = site_service.requirements_file(site.site_id)
    content = req_file.read_text(encoding="utf-8") if req_file.exists() else ""
    return {"ok": True, "content": content}


@router.post("/{site_id}/requirements")
async def add_requirement(
    site_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.get_site_by_public_id(db, site_id, current_user)
    text = (payload.get("content") or "").strip()
    if not text:
        return {"ok": True, "content": ""}
    req_file: Path = site_service.requirements_file(site.site_id)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {ts}\n{text}\n"
    if not req_file.exists():
        req_file.write_text(f"# 需求文档{entry}", encoding="utf-8")
    else:
        with req_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    return {"ok": True, "content": req_file.read_text(encoding="utf-8")}


@router.delete("/{site_id}")
async def delete_site(
    site_id: str,
    current_user: object = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await site_service.delete_site(db, site_id, current_user)
    return {"ok": True}
