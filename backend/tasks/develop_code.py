from __future__ import annotations

import asyncio

from backend.core.celery_app import celery_app
from backend.services.task_service import task_service
from backend.tasks._helpers import task_db_session


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def develop_code_task(self, task_id: str) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        async with task_db_session() as db:
            task = await task_service.run_develop_task(db, task_id)
            return task_service.serialize_task(task)

    return asyncio.run(_run())
