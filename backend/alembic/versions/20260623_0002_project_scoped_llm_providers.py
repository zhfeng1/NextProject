"""Add project scoped LLM provider configuration.

Revision ID: 20260623_0002
Revises: 20260623_0001
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0002"
down_revision = "20260623_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_llm_providers", sa.Column("scope_type", sa.String(length=16), server_default="global", nullable=False))
    op.add_column("user_llm_providers", sa.Column("project_id", sa.String(length=36), nullable=True))
    op.create_index("ix_user_llm_providers_scope_type", "user_llm_providers", ["scope_type"])
    op.create_index("ix_user_llm_providers_project_id", "user_llm_providers", ["project_id"])
    op.create_foreign_key(
        "fk_user_llm_providers_project_id_projects",
        "user_llm_providers",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_llm_providers_project_id_projects", "user_llm_providers", type_="foreignkey")
    op.drop_index("ix_user_llm_providers_project_id", table_name="user_llm_providers")
    op.drop_index("ix_user_llm_providers_scope_type", table_name="user_llm_providers")
    op.drop_column("user_llm_providers", "project_id")
    op.drop_column("user_llm_providers", "scope_type")
