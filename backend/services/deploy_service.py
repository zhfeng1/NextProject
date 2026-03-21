from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Task, TaskStatus
from backend.services.site_service import site_service
from backend.services.task_service import task_service


class DeployService:
    async def create_deploy_task(
        self,
        db: AsyncSession,
        site_id: str,
        current_user: object,
        *,
        target: str,
        options: dict[str, Any],
    ) -> Task:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        task_type = "deploy_apollo" if target == "apollo" else "deploy_local"
        task = Task(
            id=str(uuid.uuid4()),
            site_id=site.id,
            provider="",
            task_type=task_type,
            status=TaskStatus.QUEUED.value,
        )
        task.payload_json = options
        db.add(task)
        await db.commit()
        await db.refresh(task)
        await task_service.append_log(db, task, f"Deploy task created: {task_type}", source="deploy")
        task_service.enqueue_task(task)
        return task


deploy_service = DeployService()
