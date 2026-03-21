from __future__ import annotations

import asyncio

from backend.core.celery_app import celery_app
from backend.services.task_service import task_service
from backend.tasks._helpers import task_db_session


@celery_app.task(bind=True, max_retries=1)
def smoke_test_task(self, task_id: str) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        async with task_db_session() as db:
            task = await task_service.run_playwright_smoke_task(db, task_id)
            return task_service.serialize_task(task)

    return asyncio.run(_run())
