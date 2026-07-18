"""Add conversation Git cleanup lifecycle fields.

Revision ID: 20260715_0002
Revises: 20260715_0001
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260715_0002"
down_revision = "20260715_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("cleanup_status", sa.String(length=20), server_default="retained", nullable=False),
    )
    op.add_column(
        "conversations",
        sa.Column("cleanup_error", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "agent_tasks",
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(
            "UPDATE agent_tasks "
            "SET conversation_id = NULLIF(BTRIM(payload_json ->> 'conversation_id'), '') "
            "WHERE conversation_id IS NULL "
            "AND EXISTS ("
            "SELECT 1 FROM conversations c "
            "WHERE c.id = NULLIF(BTRIM(agent_tasks.payload_json ->> 'conversation_id'), '')"
            ")"
        ))
    elif bind.dialect.name == "sqlite":
        bind.execute(sa.text(
            "UPDATE agent_tasks "
            "SET conversation_id = NULLIF(TRIM(json_extract(payload_json, '$.conversation_id')), '') "
            "WHERE conversation_id IS NULL "
            "AND EXISTS ("
            "SELECT 1 FROM conversations c "
            "WHERE c.id = NULLIF(TRIM(json_extract(agent_tasks.payload_json, '$.conversation_id')), '')"
            ")"
        ))
    op.create_index("ix_agent_tasks_conversation_id", "agent_tasks", ["conversation_id"])
    op.create_foreign_key(
        "fk_agent_tasks_conversation_id_conversations",
        "agent_tasks",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_agent_tasks_conversation_id_conversations",
        "agent_tasks",
        type_="foreignkey",
    )
    op.drop_index("ix_agent_tasks_conversation_id", table_name="agent_tasks")
    op.drop_column("agent_tasks", "conversation_id")
    op.drop_column("conversations", "cleanup_error")
    op.drop_column("conversations", "cleanup_status")
