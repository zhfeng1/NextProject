from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from backend.core.config import get_settings


def _columns(inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _legacy_baseline(inspector) -> str:
    conversation_columns = _columns(inspector, "conversations")
    task_columns = _columns(inspector, "agent_tasks")
    provider_columns = _columns(inspector, "user_llm_providers")
    if {"cleanup_status", "cleanup_error"} <= conversation_columns and "conversation_id" in task_columns:
        return "20260715_0002"
    if "enabled_formats_json" in provider_columns:
        return "20260715_0001"
    if {"branch_name", "worktree_root", "git_repos_json"} <= conversation_columns:
        return "20260714_0001"
    if {"project_id", "scope_type", "repo_ids_json"} <= conversation_columns:
        return "20260702_0001"
    raise RuntimeError("Existing database schema is too old to determine a safe Alembic baseline")


def main() -> None:
    settings = get_settings()
    config_path = Path("/app/backend/alembic.ini")
    config = Config(str(config_path))
    config.set_main_option("script_location", "/app/backend/alembic")
    engine = create_engine(settings.resolved_sync_database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    versions: list[str] = []
    if "alembic_version" in tables:
        with engine.connect() as connection:
            versions = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if tables and not versions:
        baseline = _legacy_baseline(inspector)
        command.stamp(config, baseline, purge=True)
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
