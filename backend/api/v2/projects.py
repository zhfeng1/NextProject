from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.project_service import project_service
from backend.services.site_service import site_service

router = APIRouter(prefix="/projects")


@router.get("")
async def list_projects(
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    projects = await project_service.list_projects(db, user=current_user)
    result = []
    for p in projects:
        repos = await project_service.get_project_repos(db, str(p.id))
        result.append(project_service.serialize_project(p, repos))
    return {"ok": True, "projects": result}


@router.post("")
async def create_project(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    description = (payload.get("description") or "").strip()
    project = await project_service.create_project(db, current_user, name, description)
    return {"ok": True, "project": project_service.serialize_project(project, [])}


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await project_service.get_project(db, project_id, current_user)
    repos = await project_service.get_project_repos(db, project_id)
    return {"ok": True, "project": project_service.serialize_project(project, repos)}


@router.put("/{project_id}")
async def update_project(
    project_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await project_service.update_project(
        db, project_id, current_user,
        name=payload.get("name"),
        description=payload.get("description"),
    )
    repos = await project_service.get_project_repos(db, project_id)
    return {"ok": True, "project": project_service.serialize_project(project, repos)}


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await project_service.delete_project(db, project_id, current_user)
    return {"ok": True}


@router.post("/{project_id}/repos")
async def add_repo(
    project_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo_name = (payload.get("name") or "").strip()
    if not repo_name:
        return {"ok": False, "error": "name is required"}
    site = await project_service.add_repo(
        db, project_id, current_user,
        repo_name=repo_name,
        git_url=(payload.get("git_url") or "").strip() or None,
        git_branch=(payload.get("git_branch") or "").strip() or None,
        git_username=(payload.get("git_username") or "").strip() or None,
        git_password=(payload.get("git_password") or "").strip() or None,
    )
    return {"ok": True, "repo": site_service.serialize_site(site)}


@router.delete("/{project_id}/repos/{repo_id}")
async def delete_repo(
    project_id: str,
    repo_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await project_service.delete_repo(db, project_id, repo_id, current_user)
    return {"ok": True}


@router.get("/{project_id}/repos/{repo_id}/files")
async def list_repo_files(
    project_id: str,
    repo_id: str,
    path: str = Query(default=""),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await project_service.get_project(db, project_id, current_user)
    site = await site_service.get_site_by_public_id(db, repo_id, current_user)
    # [NEW-03 fix] validate repo belongs to this project
    if str(site.project_id) != str(project_id):
        raise HTTPException(status_code=404, detail="Repo not found in this project")
    repo_path = project_service.repo_root(project_id, site.name)
    data = site_service.list_site_files(site.site_id, path, override_root=repo_path)
    return {"ok": True, **data}


@router.get("/{project_id}/repos/{repo_id}/file")
async def get_repo_file(
    project_id: str,
    repo_id: str,
    path: str = Query(default=""),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await project_service.get_project(db, project_id, current_user)
    site = await site_service.get_site_by_public_id(db, repo_id, current_user)
    # [NEW-03 fix] validate repo belongs to this project
    if str(site.project_id) != str(project_id):
        raise HTTPException(status_code=404, detail="Repo not found in this project")
    repo_path = project_service.repo_root(project_id, site.name)
    data = site_service.read_site_file(site.site_id, path, override_root=repo_path)
    return {"ok": True, **data}
