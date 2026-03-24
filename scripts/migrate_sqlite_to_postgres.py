from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from backend.core.database import AsyncSessionLocal
from backend.models import (
    AppConfig,
    Organization,
    OrganizationMember,
    Site,
    SiteDeployConfig,
    SiteProviderConfig,
    Task,
    TaskLog,
    User,
)
from backend.models.enums import PlanTier, SiteStatus, TaskStatus, TaskType, UserRole


DEFAULT_SQLITE_PATH = Path("data/app.db")


@dataclass
class MigrationStats:
    app_config: int = 0
    organizations: int = 0
    users: int = 0
    sites: int = 0
    deploy_configs: int = 0
    provider_configs: int = 0
    tasks: int = 0
    task_logs: int = 0


def read_json(value: str | None) -> dict:
    if not value:
        return {}


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00").replace(" ", "T")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def normalize_task_status(value: str | None) -> TaskStatus:
    raw = (value or "queued").upper()
    try:
        return TaskStatus[raw]
    except KeyError:
        return TaskStatus.QUEUED


def normalize_task_type(value: str | None) -> TaskType:
    raw = (value or "develop_code").upper()
    try:
        return TaskType[raw]
    except KeyError:
        return TaskType.DEVELOP_CODE


def normalize_site_status(value: str | None) -> SiteStatus:
    raw = (value or "stopped").upper()
    try:
        return SiteStatus[raw]
    except KeyError:
        return SiteStatus.STOPPED


async def migrate(sqlite_path: Path, truncate: bool = False) -> MigrationStats:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    stats = MigrationStats()

    default_org_id = uuid.uuid4()
    default_user_id = uuid.uuid4()
    site_id_map: dict[str, uuid.UUID] = {}
    task_id_map: dict[str, uuid.UUID] = {}

    async with AsyncSessionLocal() as session:
        if truncate:
            for model in (TaskLog, Task, SiteProviderConfig, SiteDeployConfig, Site, OrganizationMember, User, Organization, AppConfig):
                await session.execute(delete(model))
            await session.commit()

        app_config = sqlite_conn.execute("SELECT * FROM app_config WHERE id = 1").fetchone()
        if app_config:
            config_row = AppConfig(
                id=1,
                llm_mode=app_config["llm_mode"],
                llm_base_url=app_config["llm_base_url"],
                llm_api_key=app_config["llm_api_key"],
                llm_model=app_config["llm_model"],
                codex_client_id=app_config["codex_client_id"],
                codex_client_secret=app_config["codex_client_secret"],
                codex_redirect_uri=app_config["codex_redirect_uri"],
                codex_access_token=app_config["codex_access_token"],
                codex_mcp_url=app_config["codex_mcp_url"],
                updated_at=parse_datetime(app_config["updated_at"]),
            )
            session.add(config_row)
            stats.app_config = 1

        organization = Organization(
            id=default_org_id,
            name="Default Organization",
            slug="default-org",
            plan_tier=PlanTier.FREE,
            ai_quota_monthly=100,
        )
        user = User(
            id=default_user_id,
            email="admin@nextproject.local",
            password_hash="migrated-placeholder",
            name="Migrated Admin",
            is_active=True,
            is_superuser=True,
            default_org_id=default_org_id,
        )
        session.add(organization)
        session.add(user)
        session.add(OrganizationMember(org_id=default_org_id, user_id=default_user_id, role=UserRole.OWNER))
        stats.organizations = 1
        stats.users = 1

        site_rows = sqlite_conn.execute("SELECT * FROM sub_sites ORDER BY created_at, site_id").fetchall()
        for row in site_rows:
            site_uuid = uuid.uuid4()
            site_id_map[row["site_id"]] = site_uuid
            session.add(
                Site(
                    id=site_uuid,
                    site_id=row["site_id"],
                    name=row["name"] or row["site_id"],
                    org_id=default_org_id,
                    owner_id=default_user_id,
                    status=normalize_site_status(row["status"]),
                    port=row["port"],
                    root_path=f"/generated_sites/{row['site_id']}",
                    preview_url=f"/sites/{row['site_id']}",
                    internal_url=f"http://127.0.0.1:{row['port']}" if row["port"] else None,
                    config={},
                    created_at=parse_datetime(row["created_at"]),
                    updated_at=parse_datetime(row["updated_at"]),
                )
            )
            stats.sites += 1

        deploy_rows = sqlite_conn.execute("SELECT * FROM site_deploy_config").fetchall()
        for row in deploy_rows:
            mapped_site_id = site_id_map.get(row["site_id"])
            if not mapped_site_id:
                continue
            session.add(
                SiteDeployConfig(
                    site_id=mapped_site_id,
                    target_type=row["target_type"] or "local",
                    system_api_base=row["system_api_base"] or "",
                    system_id=row["system_id"] or "",
                    app_id=row["app_id"] or "",
                    harbor_domain=row["harbor_domain"] or "",
                    harbor_domain_public=row["harbor_domain_public"] or "",
                    harbor_namespace=row["harbor_namespace"] or "",
                    module_name=row["module_name"] or "",
                    login_tel=row["login_tel"] or "",
                    login_password=row["login_password"] or "",
                    login_random=row["login_random"] or "",
                    login_path=row["login_path"] or "/apollo/user/login",
                    deploy_path=row["deploy_path"] or "/devops/cicd/v1.0/job/deployByImage",
                    extra_headers_json=read_json(row["extra_headers_json"]),
                    updated_at=parse_datetime(row["updated_at"]),
                )
            )
            stats.deploy_configs += 1

        provider_rows = sqlite_conn.execute("SELECT * FROM site_provider_config").fetchall()
        for row in provider_rows:
            mapped_site_id = site_id_map.get(row["site_id"])
            if not mapped_site_id:
                continue
            session.add(
                SiteProviderConfig(
                    site_id=mapped_site_id,
                    codex_cmd=row["codex_cmd"] or "",
                    claude_cmd=row["claude_cmd"] or "",
                    gemini_cmd=row["gemini_cmd"] or "",
                    codex_auth_cmd=row["codex_auth_cmd"] or "",
                    claude_auth_cmd=row["claude_auth_cmd"] or "",
                    gemini_auth_cmd=row["gemini_auth_cmd"] or "",
                    updated_at=parse_datetime(row["updated_at"]),
                )
            )
            stats.provider_configs += 1

        task_rows = sqlite_conn.execute("SELECT * FROM agent_tasks ORDER BY created_at, id").fetchall()
        for row in task_rows:
            mapped_site_id = site_id_map.get(row["site_id"])
            if not mapped_site_id:
                continue
            task_uuid = uuid.uuid4()
            task_id_map[row["id"]] = task_uuid
            session.add(
                Task(
                    id=task_uuid,
                    site_id=mapped_site_id,
                    task_type=normalize_task_type(row["task_type"]),
                    provider=row["provider"] or "",
                    status=normalize_task_status(row["status"]),
                    queue_name="ai-tasks" if (row["task_type"] or "") == "develop_code" else "default",
                    payload=read_json(row["payload_json"]),
                    result=read_json(row["result_json"]),
                    error=row["error"] or "",
                    created_by=default_user_id,
                    created_at=parse_datetime(row["created_at"]),
                    started_at=parse_datetime(row["started_at"]),
                    finished_at=parse_datetime(row["finished_at"]),
                )
            )
            stats.tasks += 1

        log_rows = sqlite_conn.execute("SELECT * FROM agent_task_logs ORDER BY id").fetchall()
        for row in log_rows:
            mapped_task_id = task_id_map.get(row["task_id"])
            if not mapped_task_id:
                continue
            session.add(
                TaskLog(
                    task_id=mapped_task_id,
                    ts=parse_datetime(row["ts"]) or datetime.utcnow(),
                    level=row["level"] or "INFO",
                    line=row["line"],
                )
            )
            stats.task_logs += 1

        await session.commit()

    sqlite_conn.close()
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate legacy SQLite data into the v2 PostgreSQL schema.")
    parser.add_argument("--sqlite-path", default=str(DEFAULT_SQLITE_PATH))
    parser.add_argument("--truncate", action="store_true", help="Delete v2 tables before importing.")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    stats = await migrate(Path(args.sqlite_path), truncate=args.truncate)
    print(
        json.dumps(
            {
                "ok": True,
                "stats": stats.__dict__,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(async_main())
