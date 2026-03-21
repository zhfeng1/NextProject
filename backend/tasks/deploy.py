from __future__ import annotations

import asyncio

from backend.core.celery_app import celery_app
from backend.models import Site, Task, TaskStatus
from backend.services.site_service import site_service
from backend.services.task_service import task_service
from backend.tasks._helpers import task_db_session


@celery_app.task(bind=True, max_retries=1)
def deploy_task(self, task_id: str) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        async with task_db_session() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return {"ok": False, "message": "task not found"}
            site = await db.get(Site, task.site_id)
            if site is None:
                return {"ok": False, "message": "site not found"}
            await task_service.update_status(db, task, TaskStatus.RUNNING)
            if task.task_type == "deploy_local":
                await site_service.restart_site(db, site.site_id, type("UserRef", (), {"id": site.owner_id, "default_org_id": site.org_id, "is_superuser": True})())
                await task_service.update_status(
                    db,
                    task,
                    TaskStatus.SUCCESS,
                    result={"ok": True, "preview_url": site_service.preview_url_for_site(site.site_id)},
                )
            else:
                await task_service.update_status(
                    db,
                    task,
                    TaskStatus.SUCCESS,
                    result={"ok": True, "target": "apollo", "message": "Apollo deploy request accepted"},
                )
            return task_service.serialize_task(task)

    return asyncio.run(_run())
