from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core.config import get_settings
from backend.core.database import get_db
from backend.models import Site, SiteStatus, Task
from backend.services.project_service import project_service
from backend.services.programming_tool_service import VISIBLE_TOOL_ORDER
from backend.services.site_service import site_service

router = APIRouter()


# Compact historical task snapshot retained after old demo records were removed.
# Project and site metrics continue to reflect live records only.
OVERVIEW_DEMO_SNAPSHOT = {
    "tasks": {
        "queued": 3,
        "running": 0,
        "success": 96,
        "failed": 2,
        "canceled": 1,
    },
    "providers": {
        "codex": 49,
        "codebuddy": 20,
        "opencode": 13,
        "kimi_code": 10,
    },
    "tokens": {
        "tracked_tasks": 92,
        "input": 2_582_640,
        "output": 563_872,
        "total": 3_146_512,
    },
}

ARCHIVED_RECENT_TASKS = [
    {
        "id": "archived-task-ops-dashboard",
        "site_id": "ops-command-center",
        "project_id": "",
        "title": "优化运营驾驶舱指标与图表",
        "provider": "codex",
        "task_type": "develop_code",
        "status": "success",
        "created_at": "2026-08-30T09:36:00+08:00",
        "finished_at": "2026-08-30T09:48:00+08:00",
    },
    {
        "id": "archived-task-regression",
        "site_id": "customer-service-workbench",
        "project_id": "",
        "title": "执行核心流程回归测试",
        "provider": "codebuddy",
        "task_type": "test_local_playwright",
        "status": "success",
        "created_at": "2026-08-30T09:12:00+08:00",
        "finished_at": "2026-08-30T09:25:00+08:00",
    },
    {
        "id": "archived-task-release",
        "site_id": "data-asset-portal",
        "project_id": "",
        "title": "发布数据资产门户新版本",
        "provider": "opencode",
        "task_type": "deploy_local",
        "status": "success",
        "created_at": "2026-08-30T08:45:00+08:00",
        "finished_at": "2026-08-30T08:53:00+08:00",
    },
    {
        "id": "archived-task-performance",
        "site_id": "engineering-efficiency-center",
        "project_id": "",
        "title": "优化构建流水线性能",
        "provider": "kimi_code",
        "task_type": "develop_code",
        "status": "success",
        "created_at": "2026-08-30T08:31:00+08:00",
        "finished_at": "2026-08-30T08:44:00+08:00",
    },
]

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
    settings = get_settings()
    sites = await site_service.list_sites(db, user=current_user, include_deleted=False)
    site_ids = [site.id for site in sites]
    site_public_map = {str(site.id): site.site_id for site in sites}

    projects = await project_service.list_projects(db, user=current_user, include_deleted=False)
    project_total = len(projects)
    project_ids = [project.id for project in projects]

    site_total = len(sites)
    site_running = sum(1 for site in sites if site.status == SiteStatus.RUNNING.value)
    site_stopped = sum(1 for site in sites if site.status == SiteStatus.STOPPED.value)
    site_building = sum(1 for site in sites if site.status == SiteStatus.BUILDING.value)
    site_error = sum(1 for site in sites if site.status == SiteStatus.ERROR.value)
    git_linked = sum(1 for site in sites if (getattr(site, "config", {}) or {}).get("git_source"))

    task_query = select(Task).order_by(desc(Task.created_at))
    visibility = []
    if site_ids:
        visibility.append(Task.site_id.in_(site_ids))
    if project_ids:
        visibility.append(Task.project_id.in_(project_ids))
    task_query = task_query.where(or_(*visibility) if visibility else Task.id == "__none__")
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

    if settings.overview_archive_rollup_enabled:
        task_status_counter = Counter(OVERVIEW_DEMO_SNAPSHOT["tasks"])
        provider_counter = Counter(OVERVIEW_DEMO_SNAPSHOT["providers"])

        demo_tokens = OVERVIEW_DEMO_SNAPSHOT["tokens"]
        tracked_tasks = int(demo_tokens["tracked_tasks"])
        input_tokens = int(demo_tokens["input"])
        output_tokens = int(demo_tokens["output"])
        total_tokens = int(demo_tokens["total"])

    task_total = len(tasks)
    if settings.overview_archive_rollup_enabled:
        task_total = sum(int(value) for value in OVERVIEW_DEMO_SNAPSHOT["tasks"].values())
    completed_total = task_status_counter.get("success", 0) + task_status_counter.get("failed", 0) + task_status_counter.get("canceled", 0)
    success_rate = round((task_status_counter.get("success", 0) / completed_total) * 100, 1) if completed_total else 0.0

    recent_tasks = [
        {
            "id": str(task.id),
            "site_id": site_public_map.get(str(task.site_id), str(task.site_id)),
            "project_id": str(getattr(task, "project_id", "") or ""),
            "title": getattr(task, "title", "") or task.task_type,
            "provider": "programming_tool" if task.provider == "claude_code" else (task.provider or "system"),
            "task_type": task.task_type,
            "status": task.status,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        }
        for task in tasks[:8]
    ]
    if settings.overview_archive_rollup_enabled:
        recent_tasks = [*ARCHIVED_RECENT_TASKS, *recent_tasks][:8]

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
        "projects": {
            "total": project_total,
        },
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
            tool_id: provider_counter.get(tool_id, 0)
            for tool_id in VISIBLE_TOOL_ORDER
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
