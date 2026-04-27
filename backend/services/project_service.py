from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.project import Project
from backend.models.site import Site, SiteStatus

GENERATED_SITES_ROOT = Path(
    __import__("os").environ.get("GENERATED_SITES_ROOT", "generated_sites")
)

# [ISSUE-04 fix] Repo name validation: only allow alphanumeric, hyphens, underscores, dots
REPO_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
MAX_REPO_NAME_LENGTH = 128


def validate_repo_name(name: str) -> str:
    """Validate and return sanitized repo name."""
    name = name.strip()
    if not name or len(name) > MAX_REPO_NAME_LENGTH:
        raise HTTPException(status_code=400, detail="Repo name must be 1-128 characters")
    if not REPO_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=400,
            detail="Repo name may only contain letters, digits, hyphens, underscores, and dots, and must start with a letter or digit",
        )
    return name


class ProjectService:
    # ---- paths ----

    def project_root(self, project_id: str) -> Path:
        return GENERATED_SITES_ROOT / project_id

    def repo_root(self, project_id: str, repo_name: str) -> Path:
        return self.project_root(project_id) / repo_name

    # ---- serialization ----

    def serialize_project(self, project: Project, repos: list[Site] | None = None) -> dict[str, Any]:
        result = {
            "id": str(project.id),
            "name": project.name,
            "description": project.description or "",
            "repo_count": len(repos) if repos is not None else 0,
            "created_at": project.created_at.isoformat() if getattr(project, "created_at", None) else None,
            "updated_at": project.updated_at.isoformat() if getattr(project, "updated_at", None) else None,
        }
        if repos is not None:
            from backend.services.site_service import site_service
            result["repos"] = [site_service.serialize_site(r) for r in repos]
        return result

    # ---- CRUD ----

    async def list_projects(self, db: AsyncSession, user: object, include_deleted: bool = False) -> list[Project]:
        query = select(Project)
        user_id = getattr(user, "id", None)
        org_id = getattr(user, "default_org_id", None)
        if user_id is not None:
            query = query.where(or_(Project.owner_id == user_id, Project.org_id == org_id))
        if not include_deleted:
            query = query.where(Project.deleted_at.is_(None))
        query = query.order_by(Project.created_at.asc())
        rows = await db.execute(query)
        return list(rows.scalars().all())

    async def get_project(self, db: AsyncSession, project_id: str, current_user: object) -> Project:
        project = await db.get(Project, project_id)
        if project is None or project.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Project not found")
        user_id = getattr(current_user, "id", None)
        org_id = getattr(current_user, "default_org_id", None)
        if str(project.owner_id) != str(user_id) and str(project.org_id) != str(org_id):
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    async def get_project_repos(self, db: AsyncSession, project_id: str) -> list[Site]:
        query = select(Site).where(Site.project_id == project_id, Site.deleted_at.is_(None))
        rows = await db.execute(query)
        return list(rows.scalars().all())

    async def create_project(
        self,
        db: AsyncSession,
        current_user: object,
        name: str,
        description: str = "",
    ) -> Project:
        project = Project(
            id=str(uuid.uuid4()),
            name=name.strip(),
            description=(description or "").strip(),
            owner_id=getattr(current_user, "id", None),
            org_id=getattr(current_user, "default_org_id", None),
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return project

    async def update_project(
        self,
        db: AsyncSession,
        project_id: str,
        current_user: object,
        name: str | None = None,
        description: str | None = None,
    ) -> Project:
        project = await self.get_project(db, project_id, current_user)
        if name is not None:
            project.name = name.strip()
        if description is not None:
            project.description = description.strip()
        await db.commit()
        await db.refresh(project)
        return project

    async def delete_project(self, db: AsyncSession, project_id: str, current_user: object) -> None:
        project = await self.get_project(db, project_id, current_user)
        from datetime import datetime, timezone
        project.deleted_at = datetime.now(timezone.utc)
        repos = await self.get_project_repos(db, project_id)
        for repo in repos:
            repo.deleted_at = datetime.now(timezone.utc)
        await db.commit()
        # R-05: 清理磁盘上的项目目录
        import shutil
        project_dir = self.project_root(project_id)
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)

    async def add_repo(
        self,
        db: AsyncSession,
        project_id: str,
        current_user: object,
        repo_name: str,
        git_url: str | None = None,
        git_branch: str | None = None,
        git_username: str | None = None,
        git_password: str | None = None,
    ) -> Site:
        """Add a repo to a project (blank creation or git clone)."""
        from backend.services.site_service import site_service

        project = await self.get_project(db, project_id, current_user)

        # [ISSUE-04 fix] validate repo name
        repo_name = validate_repo_name(repo_name)

        # T-04: 同一项目下仓库名唯一性检查
        existing_repos = await self.get_project_repos(db, project_id)
        if any(r.name == repo_name for r in existing_repos):
            raise HTTPException(status_code=409, detail=f"Repo '{repo_name}' already exists in this project")

        site_id = str(uuid.uuid4())
        config: dict[str, Any] = {}
        if git_url:
            config["git_source"] = {
                "url": git_url,
                "username": git_username or "",
                "branch": git_branch or "",
            }

        site = Site(
            id=str(uuid.uuid4()),
            site_id=site_id,
            name=repo_name,
            owner_id=str(project.owner_id),
            org_id=str(project.org_id),
            project_id=project_id,
            status=SiteStatus.BUILDING.value if git_url else SiteStatus.STOPPED.value,
            config=config,
        )
        db.add(site)
        await db.flush()

        if git_url:
            # [ISSUE-03 fix] encrypt git_password before storing in payload
            git_password_encrypted = ""
            if git_password:
                from backend.core.encryption import encrypt_api_key
                git_password_encrypted = encrypt_api_key(git_password)

            from backend.models.task import AgentTask
            from backend.models.enums import TaskType, TaskStatus
            task = AgentTask(
                id=str(uuid.uuid4()),
                site_id=site.id,
                task_type=TaskType.CLONE_REPO.value,
                status=TaskStatus.QUEUED.value,
                payload_json={
                    "git_url": git_url,
                    "git_branch": git_branch or "",
                    "git_username": git_username or "",
                    "git_password_encrypted": git_password_encrypted,
                    "project_id": project_id,
                    "repo_name": repo_name,
                },
            )
            db.add(task)
            await db.flush()
            await db.commit()
            from backend.services.task_service import task_service
            task_service.enqueue_task(task)
        else:
            # Blank repo: initialize at project grouped path
            repo_path = self.repo_root(project_id, repo_name)
            site_service.ensure_site_structure(site.site_id, override_root=repo_path)
            await db.commit()

        await db.refresh(site)
        return site

    async def delete_repo(
        self,
        db: AsyncSession,
        project_id: str,
        repo_id: str,
        current_user: object,
    ) -> None:
        """Delete a single repo from a project."""
        project = await self.get_project(db, project_id, current_user)
        from backend.services.site_service import site_service
        site = await site_service.get_site_by_public_id(db, repo_id, current_user)
        if str(site.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="Repo not found in this project")
        from datetime import datetime, timezone
        site.deleted_at = datetime.now(timezone.utc)
        await db.commit()
        import shutil
        repo_dir = self.repo_root(project_id, site.name)
        if repo_dir.exists():
            shutil.rmtree(repo_dir, ignore_errors=True)


project_service = ProjectService()
