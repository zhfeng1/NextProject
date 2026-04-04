"""Add projects table and sites.project_id FK.

Revision ID: 20260423_0002
Revises: 20260423_0001
"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "20260423_0002"
down_revision = "20260423_0001"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)

GENERATED_SITES_ROOT = Path(os.environ.get("GENERATED_SITES_ROOT", "generated_sites"))


def upgrade() -> None:
    # 1. 创建 projects 表
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=True),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. sites 表添加 project_id 列
    op.add_column("sites", sa.Column("project_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_sites_project_id_projects",
        "sites",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_sites_project_id", "sites", ["project_id"])

    # 3. 数据迁移：为每个现有 Site 创建同名 Project + 文件系统迁移
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, site_id, name, org_id, owner_id FROM sites WHERE deleted_at IS NULL")
    )
    for row in rows:
        project_id = str(uuid.uuid4())
        site_db_id = row[0]
        site_id = row[1]
        site_name = row[2]

        # 3a. 数据库迁移：创建 Project 并关联 Site
        bind.execute(
            sa.text(
                "INSERT INTO projects (id, name, description, org_id, owner_id) "
                "VALUES (:id, :name, '', :org_id, :owner_id)"
            ),
            {"id": project_id, "name": site_name, "org_id": row[3], "owner_id": row[4]},
        )
        bind.execute(
            sa.text("UPDATE sites SET project_id = :project_id WHERE id = :site_id"),
            {"project_id": project_id, "site_id": site_db_id},
        )

        # 3b. 文件系统迁移：generated_sites/<site_id>/ → generated_sites/<project_id>/<site_name>/
        old_path = GENERATED_SITES_ROOT / site_id
        new_path = GENERATED_SITES_ROOT / project_id / site_name
        if old_path.exists() and old_path.is_dir():
            logger.info("Migrating site files: %s -> %s", old_path, new_path)
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(old_path), str(new_path))
            # 验证复制成功后删除旧目录
            if new_path.exists():
                shutil.rmtree(str(old_path))
                logger.info("Removed old site directory: %s", old_path)
            else:
                logger.warning("File migration verification failed for %s, keeping old directory", old_path)


def downgrade() -> None:
    # 反向文件系统迁移：generated_sites/<project_id>/<site_name>/ → generated_sites/<site_id>/
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT s.site_id, s.name, s.project_id FROM sites s "
            "WHERE s.project_id IS NOT NULL AND s.deleted_at IS NULL"
        )
    )
    for row in rows:
        site_id = row[0]
        site_name = row[1]
        project_id = row[2]
        new_path = GENERATED_SITES_ROOT / project_id / site_name
        old_path = GENERATED_SITES_ROOT / site_id
        if new_path.exists() and new_path.is_dir() and not old_path.exists():
            logger.info("Reverting site files: %s -> %s", new_path, old_path)
            shutil.copytree(str(new_path), str(old_path))
            if old_path.exists():
                shutil.rmtree(str(new_path))
                # 清理空的 project 目录
                project_dir = GENERATED_SITES_ROOT / project_id
                if project_dir.exists() and not any(project_dir.iterdir()):
                    project_dir.rmdir()

    op.drop_index("ix_sites_project_id", table_name="sites")
    op.drop_constraint("fk_sites_project_id_projects", "sites", type_="foreignkey")
    op.drop_column("sites", "project_id")
    op.drop_table("projects")
