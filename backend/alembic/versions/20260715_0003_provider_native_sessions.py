"""Persist native programming tool session ids.

Revision ID: 20260715_0003
Revises: 20260715_0002
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260715_0003"
down_revision = "20260715_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("provider_session_id", sa.String(length=255), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("conversations", "provider_session_id")
