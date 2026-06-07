from __future__ import annotations

import asyncio

from backend.core.celery_app import celery_app
from backend.core.redis_lock import acquire_site_lock, release_site_lock
from backend.models import Task
from backend.services.task_service import task_service
from backend.tasks._helpers import task_db_session


@celery_app.task(bind=True, max_retries=60, default_retry_delay=30)
def develop_code_task(self, task_id: str) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        async with task_db_session() as db:
            task = await db.get(Task, task_id)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            lock_id = f"project:{task.project_id}" if getattr(task, "project_id", None) else f"site:{task.site_id}"

        # Acquire target-level lock outside the DB session.
        if not acquire_site_lock(lock_id, task_id):
            raise self.retry(countdown=30)

        try:
            async with task_db_session() as db:
                result_task = await task_service.run_develop_task(db, task_id)
                return task_service.serialize_task(result_task)
        finally:
            release_site_lock(lock_id, task_id)

    return asyncio.run(_run())
