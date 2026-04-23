"""Encrypt existing plaintext API keys with Fernet.

Revision ID: 20260423_0001
Revises: 20260331_0001
"""
from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from cryptography.fernet import Fernet

revision = "20260423_0001"
down_revision = "20260331_0001"
branch_labels = None
depends_on = None


def _get_fernet() -> Fernet:
    key = os.environ.get("FERNET_KEY", "")
    if not key:
        raise RuntimeError("FERNET_KEY environment variable is required for this migration")
    return Fernet(key.encode())


def upgrade() -> None:
    bind = op.get_bind()
    fernet = _get_fernet()
    rows = bind.execute(
        sa.text("SELECT id, api_key FROM user_llm_providers WHERE api_key IS NOT NULL AND api_key != ''")
    )
    for row in rows:
        api_key = row[1]
        if api_key.startswith("gAAAAA"):
            continue  # already encrypted
        encrypted = fernet.encrypt(api_key.encode()).decode()
        bind.execute(
            sa.text("UPDATE user_llm_providers SET api_key = :key WHERE id = :id"),
            {"key": encrypted, "id": row[0]},
        )


def downgrade() -> None:
    bind = op.get_bind()
    fernet = _get_fernet()
    rows = bind.execute(
        sa.text("SELECT id, api_key FROM user_llm_providers WHERE api_key IS NOT NULL AND api_key != ''")
    )
    for row in rows:
        api_key = row[1]
        if not api_key.startswith("gAAAAA"):
            continue  # not encrypted
        try:
            decrypted = fernet.decrypt(api_key.encode()).decode()
            bind.execute(
                sa.text("UPDATE user_llm_providers SET api_key = :key WHERE id = :id"),
                {"key": decrypted, "id": row[0]},
            )
        except Exception:
            pass  # skip rows that fail to decrypt
