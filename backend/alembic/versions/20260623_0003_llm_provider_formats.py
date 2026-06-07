"""Add multi-format LLM provider configuration.

Revision ID: 20260623_0003
Revises: 20260623_0002
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260623_0003"
down_revision = "20260623_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    op.add_column(
        "user_llm_providers",
        sa.Column(
            "formats_json",
            postgresql.JSONB() if is_pg else sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )
    if is_pg:
        op.execute("UPDATE user_llm_providers SET formats_json = jsonb_build_array(format) WHERE format IN ('responses', 'messages')")
    else:
        op.execute("UPDATE user_llm_providers SET formats_json = json_array(format) WHERE format IN ('responses', 'messages')")


def downgrade() -> None:
    op.drop_column("user_llm_providers", "formats_json")
