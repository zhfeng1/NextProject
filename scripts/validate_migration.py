from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from sqlalchemy import func, select

from backend.core.database import AsyncSessionLocal
from backend.models import AppConfig, Site, SiteDeployConfig, SiteProviderConfig, Task, TaskLog


DEFAULT_SQLITE_PATH = Path("data/app.db")


async def validate(sqlite_path: Path) -> dict:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_counts = {
        "app_config": sqlite_conn.execute("SELECT COUNT(*) FROM app_config").fetchone()[0],
        "sub_sites": sqlite_conn.execute("SELECT COUNT(*) FROM sub_sites").fetchone()[0],
        "site_deploy_config": sqlite_conn.execute("SELECT COUNT(*) FROM site_deploy_config").fetchone()[0],
        "site_provider_config": sqlite_conn.execute("SELECT COUNT(*) FROM site_provider_config").fetchone()[0],
        "agent_tasks": sqlite_conn.execute("SELECT COUNT(*) FROM agent_tasks").fetchone()[0],
        "agent_task_logs": sqlite_conn.execute("SELECT COUNT(*) FROM agent_task_logs").fetchone()[0],
    }
    sqlite_conn.close()

    async with AsyncSessionLocal() as session:
        postgres_counts = {
            "app_config": await session.scalar(select(func.count()).select_from(AppConfig)),
            "sites": await session.scalar(select(func.count()).select_from(Site)),
            "site_deploy_configs": await session.scalar(select(func.count()).select_from(SiteDeployConfig)),
            "site_provider_configs": await session.scalar(select(func.count()).select_from(SiteProviderConfig)),
            "tasks": await session.scalar(select(func.count()).select_from(Task)),
            "task_logs": await session.scalar(select(func.count()).select_from(TaskLog)),
        }

    checks = {
        "app_config": sqlite_counts["app_config"] == postgres_counts["app_config"],
        "sites": sqlite_counts["sub_sites"] == postgres_counts["sites"],
        "site_deploy_configs": sqlite_counts["site_deploy_config"] == postgres_counts["site_deploy_configs"],
        "site_provider_configs": sqlite_counts["site_provider_config"] == postgres_counts["site_provider_configs"],
        "tasks": sqlite_counts["agent_tasks"] == postgres_counts["tasks"],
        "task_logs": sqlite_counts["agent_task_logs"] == postgres_counts["task_logs"],
    }
    return {
        "ok": all(checks.values()),
        "sqlite_counts": sqlite_counts,
        "postgres_counts": postgres_counts,
        "checks": checks,
    }


async def async_main() -> None:
    result = await validate(DEFAULT_SQLITE_PATH)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(async_main())
