"""Add enabled formats to project LLM providers.

Revision ID: 20260715_0001
Revises: 20260714_0001
"""
from __future__ import annotations

from typing import Any, Mapping

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260715_0001"
down_revision = "20260714_0001"
branch_labels = None
depends_on = None

SUPPORTED_FORMATS = ("responses", "messages", "chat_completions")


def _normalized_formats(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("formats_json") or []
    if isinstance(raw, str):
        raw = [raw]
    formats = [str(item).strip() for item in raw if str(item).strip() in SUPPORTED_FORMATS]
    legacy = str(row.get("format") or "").strip()
    if legacy in SUPPORTED_FORMATS and legacy not in formats:
        formats.insert(0, legacy)
    if not formats:
        formats = ["responses"]
    return list(dict.fromkeys(formats))


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    op.add_column(
        "user_llm_providers",
        sa.Column(
            "enabled_formats_json",
            postgresql.JSONB() if is_pg else sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )

    providers = sa.table(
        "user_llm_providers",
        sa.column("id", sa.String()),
        sa.column("user_id", sa.String()),
        sa.column("scope_type", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("format", sa.String()),
        sa.column("formats_json", sa.JSON()),
        sa.column("enabled_formats_json", sa.JSON()),
        sa.column("is_default", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
    )
    rows = list(
        bind.execute(
            sa.select(providers).order_by(
                providers.c.user_id,
                providers.c.scope_type,
                providers.c.project_id,
                providers.c.is_default.desc(),
                providers.c.created_at,
                providers.c.id,
            )
        ).mappings()
    )

    claimed: set[tuple[str, str, str, str]] = set()
    for row in rows:
        scope_key = (
            str(row.get("user_id") or ""),
            str(row.get("scope_type") or "global"),
            str(row.get("project_id") or ""),
        )
        enabled: list[str] = []
        for fmt in _normalized_formats(row):
            key = (*scope_key, fmt)
            if key in claimed:
                continue
            claimed.add(key)
            enabled.append(fmt)
        bind.execute(
            providers.update()
            .where(providers.c.id == row["id"])
            .values(enabled_formats_json=enabled)
        )


def downgrade() -> None:
    op.drop_column("user_llm_providers", "enabled_formats_json")
