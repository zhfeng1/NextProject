from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260323_0004"
down_revision = "20260323_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    id_col = sa.Column("id", postgresql.UUID(as_uuid=True) if is_pg else sa.String(36), primary_key=True)
    user_id_col = sa.Column("user_id", postgresql.UUID(as_uuid=True) if is_pg else sa.String(36), nullable=False)
    models_col = sa.Column("models", postgresql.JSONB() if is_pg else sa.JSON(), nullable=False, server_default="[]")

    op.create_table(
        "user_llm_providers",
        id_col,
        user_id_col,
        sa.Column("name", sa.String(100), nullable=False, server_default=""),
        sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("api_key", sa.Text(), nullable=False, server_default=""),
        models_col,
        sa.Column("format", sa.String(20), nullable=False, server_default="responses"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_llm_providers_user_id", ondelete="CASCADE"),
    )
    op.create_index("ix_user_llm_providers_user_id", "user_llm_providers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_llm_providers_user_id")
    op.drop_table("user_llm_providers")
