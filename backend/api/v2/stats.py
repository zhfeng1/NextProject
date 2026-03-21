from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core.database import get_db
from backend.models import Site, SiteStatus, Task
from backend.services.site_service import site_service

router = APIRouter()


def _extract_token_usage(result: dict[str, Any] | None) -> tuple[int, int, int]:
    payload = result or {}
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else payload
    input_tokens = int(
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("prompt_token_count")
        or 0
    )
    output_tokens = int(
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or usage.get("completion_token_count")
        or 0
    )
    total_tokens = int(
        usage.get("total_tokens")
        or usage.get("total_token_count")
        or (input_tokens + output_tokens)
        or 0
    )
    return input_tokens, output_tokens, total_tokens


@router.get("/stats/overview")
async def get_overview_stats(
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sites = await site_service.list_sites(db, user=current_user, include_deleted=False)
    site_ids = [site.id for site in sites]
    site_public_map = {str(site.id): site.site_id for site in sites}

    site_total = len(sites)
    site_running = sum(1 for site in sites if site.status == SiteStatus.RUNNING.value)
    site_stopped = sum(1 for site in sites if site.status == SiteStatus.STOPPED.value)
    site_building = sum(1 for site in sites if site.status == SiteStatus.BUILDING.value)
    site_error = sum(1 for site in sites if site.status == SiteStatus.ERROR.value)
    git_linked = sum(1 for site in sites if (getattr(site, "config", {}) or {}).get("git_source"))

    task_query = select(Task).order_by(desc(Task.created_at))
    if site_ids:
        task_query = task_query.where(Task.site_id.in_(site_ids))
    else:
        task_query = task_query.where(Task.site_id.in_([]))
    tasks = list((await db.execute(task_query)).scalars().all())

    task_status_counter = Counter(getattr(task, "status", "") or "" for task in tasks)
    provider_counter = Counter(
        (getattr(task, "provider", "") or "other")
        for task in tasks
        if getattr(task, "task_type", "") == "develop_code"
    )

    tracked_tasks = 0
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    for task in tasks:
        in_tok, out_tok, total_tok = _extract_token_usage(getattr(task, "result_json", None) or {})
        if in_tok or out_tok or total_tok:
            tracked_tasks += 1
            input_tokens += in_tok
            output_tokens += out_tok
            total_tokens += total_tok

    task_total = len(tasks)
    completed_total = task_status_counter.get("success", 0) + task_status_counter.get("failed", 0) + task_status_counter.get("canceled", 0)
    success_rate = round((task_status_counter.get("success", 0) / completed_total) * 100, 1) if completed_total else 0.0

    recent_tasks = [
        {
            "id": str(task.id),
            "site_id": site_public_map.get(str(task.site_id), str(task.site_id)),
            "provider": task.provider or "system",
            "task_type": task.task_type,
            "status": task.status,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        }
        for task in tasks[:8]
    ]

    recent_sites = [
        {
            "site_id": site.site_id,
            "name": site.name,
            "status": site.status,
            "created_at": site.created_at.isoformat() if site.created_at else None,
            "source": "git" if (getattr(site, "config", {}) or {}).get("git_source") else "blank",
        }
        for site in sorted(sites, key=lambda item: item.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:6]
    ]

    template_total = sum(1 for site in sites if getattr(site, "template_id", None))

    return {
        "ok": True,
        "sites": {
            "total": site_total,
            "running": site_running,
            "stopped": site_stopped,
            "building": site_building,
            "error": site_error,
            "git_linked": git_linked,
        },
        "tasks": {
            "total": task_total,
            "queued": task_status_counter.get("queued", 0),
            "running": task_status_counter.get("running", 0),
            "success": task_status_counter.get("success", 0),
            "failed": task_status_counter.get("failed", 0),
            "canceled": task_status_counter.get("canceled", 0),
            "success_rate": success_rate,
        },
        "providers": {
            "codex": provider_counter.get("codex", 0),
            "claude_code": provider_counter.get("claude_code", 0),
            "gemini_cli": provider_counter.get("gemini_cli", 0),
        },
        "tokens": {
            "tracked": tracked_tasks > 0,
            "tracked_tasks": tracked_tasks,
            "input": input_tokens,
            "output": output_tokens,
            "total": total_tokens,
        },
        "recent_tasks": recent_tasks,
        "recent_sites": recent_sites,
        "templates": {
            "linked_sites": int(template_total),
        },
    }
