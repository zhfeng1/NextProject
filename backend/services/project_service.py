from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.project import Project
from backend.models.site import Site, SiteStatus
from backend.services.site_scaffold_service import python_vue_site_config, site_scaffold_service

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

    @staticmethod
    def _current_branch(repo_root: Path) -> str:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

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
        create_default_repo: bool = True,
        default_repo_name: str = "app",
        starter: str = "python-vue",
    ) -> Project:
        if starter != "python-vue":
            raise HTTPException(status_code=400, detail="Only python-vue starter is supported")
        project = Project(
            id=str(uuid.uuid4()),
            name=name.strip(),
            description=(description or "").strip(),
            owner_id=getattr(current_user, "id", None),
            org_id=getattr(current_user, "default_org_id", None),
        )
        db.add(project)
        try:
            await db.flush()
            if create_default_repo:
                repo_name = validate_repo_name(default_repo_name or "app")
                await self._create_starter_repo_record(
                    db,
                    project=project,
                    repo_name=repo_name,
                    starter=starter,
                )
            await db.commit()
        except Exception:
            await db.rollback()
            project_dir = self.project_root(str(project.id))
            if project_dir.exists():
                shutil.rmtree(project_dir, ignore_errors=True)
            raise
        await db.refresh(project)
        return project

    async def _create_starter_repo_record(
        self,
        db: AsyncSession,
        *,
        project: Project,
        repo_name: str,
        starter: str = "python-vue",
    ) -> Site:
        if starter != "python-vue":
            raise HTTPException(status_code=400, detail="Only python-vue starter is supported")

        from backend.services.site_service import site_service

        rows = await db.execute(select(Site))
        all_sites = list(rows.scalars().all())
        site = Site(
            id=str(uuid.uuid4()),
            site_id=str(uuid.uuid4()),
            name=repo_name,
            owner_id=str(project.owner_id),
            org_id=str(project.org_id),
            project_id=str(project.id),
            status=SiteStatus.STOPPED.value,
            port=site_service._next_port(all_sites),
            config=python_vue_site_config(),
        )
        db.add(site)
        await db.flush()
        repo_root = self.repo_root(str(project.id), repo_name)
        site_scaffold_service.initialize_python_vue_site(repo_root)
        site.main_branch = self._current_branch(repo_root)
        return site

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
        starter: str = "python-vue",
        start_command: str | None = None,
    ) -> Site:
        """Add a repo to a project (blank creation or git clone)."""
        from backend.services.site_service import site_service

        project = await self.get_project(db, project_id, current_user)

        if git_url:
            embedded_username, embedded_password = site_service.git_url_credentials(git_url)
            git_username = git_username or embedded_username
            git_password = git_password or embedded_password
            git_url = site_service.sanitize_git_url(git_url)

        # [ISSUE-04 fix] validate repo name
        repo_name = validate_repo_name(repo_name)

        # T-04: 同一项目下仓库名唯一性检查
        existing_repos = await self.get_project_repos(db, project_id)
        if any(r.name == repo_name for r in existing_repos):
            raise HTTPException(status_code=409, detail=f"Repo '{repo_name}' already exists in this project")

        if starter not in {"python-vue", "empty"}:
            raise HTTPException(status_code=400, detail="starter must be python-vue or empty")

        site_id = str(uuid.uuid4())
        config: dict[str, Any] = {}
        if git_url:
            config["git_source"] = {
                "url": git_url,
                "username": git_username or "",
                "branch": git_branch or "",
            }
            config["source_type"] = "git"
            if start_command:
                config["start_command"] = start_command
        elif starter == "python-vue":
            config = python_vue_site_config()
        else:
            config = {"source_type": "legacy"}

        rows = await db.execute(select(Site))
        all_sites = list(rows.scalars().all())

        site = Site(
            id=str(uuid.uuid4()),
            site_id=site_id,
            name=repo_name,
            owner_id=str(project.owner_id),
            org_id=str(project.org_id),
            project_id=project_id,
            status=SiteStatus.BUILDING.value if git_url else SiteStatus.STOPPED.value,
            port=site_service._next_port(all_sites),
            main_branch=git_branch or "",
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
                    "start_command": start_command or "",
                },
            )
            db.add(task)
            await db.flush()
            await db.commit()
            from backend.services.task_service import task_service
            task_service.enqueue_task(task)
        else:
            repo_path = self.repo_root(project_id, repo_name)
            try:
                if starter == "python-vue":
                    site_scaffold_service.initialize_python_vue_site(repo_path)
                else:
                    repo_path.mkdir(parents=True, exist_ok=True)
                    site_scaffold_service.ensure_support_dirs(repo_path)
                    site_scaffold_service.initialize_git_repo(repo_path, message="Initial empty repo")
                site.main_branch = self._current_branch(repo_path)
                await db.commit()
            except Exception:
                await db.rollback()
                shutil.rmtree(repo_path, ignore_errors=True)
                raise

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
        repo_dir = site_service.resolve_site_root(site)
        if repo_dir.exists():
            shutil.rmtree(repo_dir, ignore_errors=True)

    async def update_repo_main_branch(
        self,
        db: AsyncSession,
        project_id: str,
        repo_id: str,
        current_user: object,
        main_branch: str,
    ) -> Site:
        project = await self.get_project(db, project_id, current_user)
        from backend.services.site_service import site_service
        from backend.services.conversation_git_service import conversation_git_service

        site = await site_service.get_site_by_public_id(db, repo_id, current_user)
        if str(site.project_id) != str(project.id):
            raise HTTPException(status_code=404, detail="Repo not found in this project")
        repo_root = self.repo_root(project_id, site.name)
        site.main_branch = conversation_git_service.set_main_branch(site, repo_root, main_branch)
        await db.commit()
        await db.refresh(site)
        return site

    async def get_repo_git_graph(
        self,
        db: AsyncSession,
        project_id: str,
        repo_id: str,
        current_user: object,
        *,
        branch: str = "",
        limit: int = 200,
        skip: int = 0,
    ) -> dict[str, Any]:
        from backend.services.conversation_git_service import conversation_git_service
        from backend.services.git_history_service import git_history_service
        from backend.services.site_service import site_service

        project = await self.get_project(db, project_id, current_user)
        site = await site_service.get_site_by_public_id(db, repo_id, current_user)
        if str(site.project_id) != str(project.id):
            raise HTTPException(status_code=404, detail="Repo not found in this project")
        expected_repo = self.repo_root(project_id, site.name)
        repo = git_history_service.ensure_repository_path(
            expected_repo,
            boundary=self.project_root(project_id),
        )
        main_branch = conversation_git_service.resolve_main_branch(site, repo)
        selected_branch = (branch or main_branch).strip()
        if not git_history_service.local_branch_exists(repo, selected_branch):
            raise HTTPException(status_code=404, detail=f"本地分支不存在: {selected_branch}")
        return git_history_service.graph(
            repo=repo,
            site_id=site.site_id,
            name=site.name,
            branch=selected_branch,
            default_branch=main_branch,
            scope="project",
            limit=limit,
            skip=skip,
        )

    async def rollback_repo_to_commit(
        self,
        db: AsyncSession,
        project_id: str,
        repo_id: str,
        current_user: object,
        *,
        commit_sha: str,
        branch: str = "",
    ) -> tuple[object, dict[str, Any]]:
        from backend.models.repo_git_operation import RepoGitOperation
        from backend.models.task import AgentTask, TaskStatus
        from backend.services.conversation_git_service import conversation_git_service
        from backend.services.git_history_service import COMMIT_SHA_PATTERN, git_history_service
        from backend.services.site_service import site_service

        if not COMMIT_SHA_PATTERN.fullmatch(commit_sha or ""):
            raise HTTPException(status_code=400, detail="commit_sha 必须是完整的 40 位 Commit SHA")
        project = await self.get_project(db, project_id, current_user)
        site = await site_service.get_site_by_public_id(db, repo_id, current_user)
        if str(site.project_id) != str(project.id):
            raise HTTPException(status_code=404, detail="Repo not found in this project")
        expected_repo = self.repo_root(project_id, site.name)
        repo = git_history_service.ensure_repository_path(
            expected_repo,
            boundary=self.project_root(project_id),
        )
        main_branch = conversation_git_service.resolve_main_branch(site, repo)
        requested_branch = branch.strip()
        if requested_branch and requested_branch != main_branch:
            raise HTTPException(status_code=409, detail="项目仓库仅支持回滚配置的主分支")

        async with git_history_service.project_lock(project_id):
            running_rows = await db.execute(
                select(AgentTask.id).where(
                    AgentTask.project_id == project_id,
                    AgentTask.status.in_([TaskStatus.QUEUED.value, TaskStatus.RUNNING.value]),
                ).limit(1)
            )
            if running_rows.scalar_one_or_none() is not None:
                raise HTTPException(status_code=409, detail="项目仍有排队中或运行中的任务，不能回滚主分支")

            operation = RepoGitOperation(
                project_id=project_id,
                site_id=site.site_id,
                conversation_id=None,
                user_id=str(getattr(current_user, "id", "")),
                scope="project",
                operation="rollback",
                repo_name=site.name,
                branch=main_branch,
                target_sha=commit_sha.lower(),
                status="running",
            )
            db.add(operation)
            await db.commit()
            try:
                before_sha, after_sha = git_history_service.rollback_branch(
                    repo=repo,
                    branch=main_branch,
                    target_sha=commit_sha,
                    expected_worktree=repo,
                )
                operation.before_sha = before_sha
                operation.after_sha = after_sha
                operation.status = "success"
                operation.error = ""
                await db.commit()
                await db.refresh(operation)
            except Exception as exc:
                operation.status = "failed"
                operation.error = str(getattr(exc, "detail", exc))[:2000]
                await db.commit()
                raise

        graph = await self.get_repo_git_graph(
            db,
            project_id,
            repo_id,
            current_user,
            branch=main_branch,
        )
        return operation, graph


project_service = ProjectService()
