"""Add project scoped conversations.

Revision ID: 20260702_0001
Revises: 20260623_0003
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260702_0001"
down_revision = "20260623_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("project_id", sa.String(length=36), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("scope_type", sa.String(length=16), server_default="site", nullable=False),
    )
    op.add_column(
        "conversations",
        sa.Column("repo_ids_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.create_index("ix_conversations_project_id", "conversations", ["project_id"])
    op.create_index("ix_conversations_scope_type", "conversations", ["scope_type"])
    op.create_foreign_key(
        "fk_conversations_project_id_projects",
        "conversations",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_conversations_project_id_projects", "conversations", type_="foreignkey")
    op.drop_index("ix_conversations_scope_type", table_name="conversations")
    op.drop_index("ix_conversations_project_id", table_name="conversations")
    op.drop_column("conversations", "repo_ids_json")
    op.drop_column("conversations", "scope_type")
    op.drop_column("conversations", "project_id")
