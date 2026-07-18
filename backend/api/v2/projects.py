from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db, require_role
from backend.services.git_history_service import git_history_service
from backend.services.project_service import project_service
from backend.services.site_service import site_service
from backend.services.task_service import task_service

router = APIRouter(prefix="/projects")


def _payload_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


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
    project = await project_service.create_project(
        db,
        current_user,
        name,
        description,
        create_default_repo=_payload_bool(payload.get("create_default_repo"), default=True),
        default_repo_name=(payload.get("default_repo_name") or "app").strip(),
        starter=(payload.get("starter") or "python-vue").strip(),
    )
    repos = await project_service.get_project_repos(db, str(project.id))
    return {"ok": True, "project": project_service.serialize_project(project, repos)}


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


@router.post("/{project_id}/tasks")
async def create_project_task(
    project_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await task_service.create_project_task(db, current_user, project_id, payload, enqueue=True)
    return {"ok": True, "task_id": str(task.id), "task": await task_service.serialize_task_detail(db, task)}


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
        starter=(payload.get("starter") or "python-vue").strip(),
        start_command=(payload.get("start_command") or "").strip() or None,
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


@router.put("/{project_id}/repos/{repo_id}/main-branch")
async def update_repo_main_branch(
    project_id: str,
    repo_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await project_service.update_repo_main_branch(
        db,
        project_id,
        repo_id,
        current_user,
        main_branch=str(payload.get("main_branch") or ""),
    )
    return {"ok": True, "repo": site_service.serialize_site(site)}


@router.get("/{project_id}/repos/{repo_id}/git/graph")
async def get_repo_git_graph(
    project_id: str,
    repo_id: str,
    branch: str = Query(default="", max_length=255),
    limit: int = Query(default=200, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    graph = await project_service.get_repo_git_graph(
        db,
        project_id,
        repo_id,
        current_user,
        branch=branch,
        limit=limit,
        skip=skip,
    )
    return {"ok": True, "graph": graph}


@router.post("/{project_id}/repos/{repo_id}/git/rollback")
async def rollback_repo_commit(
    project_id: str,
    repo_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(require_role("developer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    operation, graph = await project_service.rollback_repo_to_commit(
        db,
        project_id,
        repo_id,
        current_user,
        commit_sha=str(payload.get("commit_sha") or "").strip(),
        branch=str(payload.get("branch") or "").strip(),
    )
    return {
        "ok": True,
        "operation": git_history_service.serialize_operation(operation),
        "graph": graph,
    }


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
