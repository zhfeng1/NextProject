from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260323_0002"
down_revision = "20260320_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    user_id_col = sa.Column(
        "user_id",
        postgresql.UUID(as_uuid=True) if is_pg else sa.String(36),
        nullable=False,
    )

    op.create_table(
        "user_configs",
        user_id_col,
        sa.Column("llm_mode", sa.String(length=32), nullable=False, server_default="responses"),
        sa.Column("llm_base_url", sa.String(length=500), nullable=False, server_default="https://api.openai.com/v1"),
        sa.Column("llm_api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("llm_model", sa.String(length=128), nullable=False, server_default="gpt-4.1-mini"),
        sa.Column("codex_client_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("codex_client_secret", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("codex_redirect_uri", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("codex_access_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("codex_mcp_url", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_configs_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_configs"),
    )


def downgrade() -> None:
    op.drop_table("user_configs")
