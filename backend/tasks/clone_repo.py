from __future__ import annotations

import asyncio

from backend.core.celery_app import celery_app
from backend.core.redis_lock import acquire_site_lock, release_site_lock
from backend.models import AgentTask
from backend.models.enums import TaskStatus, SiteStatus
from backend.models.site import Site
from backend.tasks._helpers import task_db_session


@celery_app.task(bind=True, max_retries=60, default_retry_delay=30)
def clone_repo_task(self, task_id: str) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        async with task_db_session() as db:
            task = await db.get(AgentTask, task_id)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            site_id = str(task.site_id)
            payload = task.payload_json or {}

        if not acquire_site_lock(site_id, task_id):
            raise self.retry(countdown=30)

        try:
            async with task_db_session() as db:
                task = await db.get(AgentTask, task_id)
                site = await db.get(Site, str(task.site_id))
                if site is None:
                    raise ValueError(f"Site not found: {task.site_id}")

                payload = task.payload_json or {}
                git_url = payload.get("git_url", "")
                git_branch = payload.get("git_branch", "")
                git_username = payload.get("git_username", "")
                project_id = payload.get("project_id", "")
                repo_name = payload.get("repo_name", site.name)

                # [ISSUE-03 fix] decrypt git_password
                git_password = ""
                encrypted_pw = payload.get("git_password_encrypted", "")
                if encrypted_pw:
                    from backend.core.encryption import decrypt_api_key
                    git_password = decrypt_api_key(encrypted_pw)

                from backend.services.site_service import site_service
                from backend.services.project_service import project_service

                clone_root = project_service.repo_root(project_id, repo_name) if project_id else None

                try:
                    site_service.clone_site_repository(
                        site.site_id,
                        git_url,
                        git_username=git_username,
                        git_password=git_password,
                        git_branch=git_branch,
                        override_root=clone_root,
                    )
                    site.status = SiteStatus.STOPPED.value
                    task.status = TaskStatus.SUCCESS.value
                except Exception as exc:
                    site.status = SiteStatus.ERROR.value
                    task.status = TaskStatus.FAILED.value
                    task.payload_json = {**(task.payload_json or {}), "error": str(exc)}
                    raise
                finally:
                    await db.commit()

                from backend.services.task_service import task_service
                return task_service.serialize_task(task)
        finally:
            release_site_lock(site_id, task_id)

    return asyncio.run(_run())
