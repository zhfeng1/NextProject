from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.task_service import task_service


class MultiAgentService:
    async def parallel_develop(
        self,
        db: AsyncSession,
        *,
        site_id: str,
        requirement: str,
        current_user: object,
        agents: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        selected_agents = agents or ["codex", "claude_code", "gemini_cli"]
        tasks = []
        for provider in selected_agents:
            task = await task_service.create_task(
                db=db,
                current_user=current_user,
                site_id=site_id,
                task_type="develop_code",
                provider=provider,
                payload_data={"prompt": f"{provider}：{requirement}", "provider": provider},
                enqueue=True,
            )
            tasks.append(task_service.serialize_task(task))
        return tasks


multi_agent_service = MultiAgentService()
