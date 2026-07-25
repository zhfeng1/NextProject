from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AgentTask, SiteStatus, SiteVersion, TaskStatus
from backend.services.git_history_service import git_history_service
from backend.services.site_service import site_service
from backend.services.site_version_git_service import SiteVersionCommit, site_version_git_service


class VersionService:
    def serialize_version(self, version: SiteVersion) -> dict[str, Any]:
        return {
            "id": str(version.id),
            "site_id": str(version.site_id),
            "version_number": version.version_number,
            "commit_sha": version.commit_sha,
            "commit_message": version.commit_message,
            "diff_summary": version.diff_summary or {},
            "is_deployed": bool(version.is_deployed),
            "created_at": version.created_at.isoformat() if version.created_at else None,
        }

    async def list_versions(self, db: AsyncSession, site_id: str, current_user: object) -> list[SiteVersion]:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        rows = await db.execute(
            select(SiteVersion).where(SiteVersion.site_id == site.id).order_by(SiteVersion.version_number.desc())
        )
        return list(rows.scalars().all())

    @staticmethod
    def _lock_name(site: object) -> str:
        project_id = str(getattr(site, "project_id", "") or "")
        return f"project:{project_id}" if project_id else f"site:{getattr(site, 'id')}"

    async def _ensure_no_active_tasks(self, db: AsyncSession, site: object) -> None:
        conditions = [AgentTask.site_id == getattr(site, "id")]
        project_id = getattr(site, "project_id", None)
        if project_id:
            conditions.append(AgentTask.project_id == project_id)
        rows = await db.execute(
            select(AgentTask.id).where(
                or_(*conditions),
                AgentTask.status.in_([TaskStatus.QUEUED.value, TaskStatus.RUNNING.value]),
            ).limit(1)
        )
        if rows.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="站点仍有排队中或运行中的任务，不能创建版本或回滚")

    async def _latest_version(self, db: AsyncSession, site_db_id: str) -> SiteVersion | None:
        rows = await db.execute(
            select(SiteVersion)
            .where(SiteVersion.site_id == site_db_id)
            .order_by(SiteVersion.version_number.desc())
            .limit(1)
        )
        return rows.scalar_one_or_none()

    async def _persist_git_version(
        self,
        *,
        db: AsyncSession,
        site_db_id: str,
        version_number: int,
        parent_version: SiteVersion | None,
        git_commit: SiteVersionCommit,
        commit_message: str,
        created_by: str,
        extra_diff: dict[str, Any] | None = None,
        preserve_worktree_on_failure: bool,
    ) -> SiteVersion:
        diff_summary = {**git_commit.diff_summary, **(extra_diff or {})}
        version = SiteVersion(
            id=str(uuid.uuid4()),
            site_id=site_db_id,
            version_number=version_number,
            parent_version_id=str(parent_version.id) if parent_version else None,
            commit_sha=git_commit.commit_sha,
            commit_message=commit_message,
            diff_summary=diff_summary,
            created_by=created_by,
        )
        db.add(version)
        try:
            await db.commit()
            await db.refresh(version)
        except Exception:
            await db.rollback()
            site_version_git_service.compensate(
                git_commit,
                preserve_worktree=preserve_worktree_on_failure,
            )
            raise
        return version

    async def create_snapshot(
        self,
        *,
        db: AsyncSession,
        site_id: str,
        commit_message: str,
        created_by: str,
        current_user: object,
    ) -> SiteVersion:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        root = site_service.resolve_site_root(site)
        if not root.exists():
            if getattr(site, "project_id", None):
                raise HTTPException(status_code=409, detail="项目仓库尚未准备完成")
            site_service.initialize_blank_site(root)
        else:
            site_service.ensure_support_dirs(root)

        async with git_history_service.repository_lock(
            self._lock_name(site),
            busy_message="站点正在执行任务或其他 Git 操作，请稍后重试",
        ):
            await self._ensure_no_active_tasks(db, site)
            parent_version = await self._latest_version(db, str(site.id))
            version_number = int(parent_version.version_number if parent_version else 0) + 1
            git_commit = site_version_git_service.create_snapshot(
                site=site,
                repo=root,
                version_number=version_number,
                message=commit_message,
            )
            return await self._persist_git_version(
                db=db,
                site_db_id=str(site.id),
                version_number=version_number,
                parent_version=parent_version,
                git_commit=git_commit,
                commit_message=commit_message,
                created_by=created_by,
                extra_diff={"operation": "snapshot", "branch": git_commit.branch},
                preserve_worktree_on_failure=True,
            )

    async def rollback_to_version(
        self,
        db: AsyncSession,
        site_id: str,
        version_number: int,
        current_user: object,
    ) -> tuple[SiteVersion, SiteVersion]:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        root = site_service.resolve_site_root(site)
        if not root.exists():
            raise HTTPException(status_code=409, detail="站点仓库尚未准备完成")

        async with git_history_service.repository_lock(
            self._lock_name(site),
            busy_message="站点正在执行任务或其他 Git 操作，请稍后重试",
        ):
            await self._ensure_no_active_tasks(db, site)
            rows = await db.execute(
                select(SiteVersion).where(
                    SiteVersion.site_id == site.id,
                    SiteVersion.version_number == version_number,
                )
            )
            target_version = rows.scalar_one_or_none()
            if target_version is None:
                raise HTTPException(status_code=404, detail=f"Version {version_number} not found")

            parent_version = await self._latest_version(db, str(site.id))
            new_version_number = int(parent_version.version_number if parent_version else 0) + 1
            commit_message = f"Rollback to version v{target_version.version_number}"
            was_running = str(getattr(site, "status", "")) == SiteStatus.RUNNING.value
            if was_running:
                site_service._stop_site_process(site.site_id)
            try:
                git_commit = site_version_git_service.create_rollback(
                    site=site,
                    repo=root,
                    target_version_number=target_version.version_number,
                    target_commit_sha=target_version.commit_sha,
                    new_version_number=new_version_number,
                    message=commit_message,
                )
                version = await self._persist_git_version(
                    db=db,
                    site_db_id=str(site.id),
                    version_number=new_version_number,
                    parent_version=parent_version,
                    git_commit=git_commit,
                    commit_message=commit_message,
                    created_by=str(getattr(current_user, "id", "")),
                    extra_diff={
                        "operation": "rollback",
                        "branch": git_commit.branch,
                        "restored_from_version": target_version.version_number,
                        "restored_from_commit": target_version.commit_sha,
                    },
                    preserve_worktree_on_failure=False,
                )
            finally:
                if was_running:
                    site_service._run_site_process(site)
            return version, target_version


version_service = VersionService()
