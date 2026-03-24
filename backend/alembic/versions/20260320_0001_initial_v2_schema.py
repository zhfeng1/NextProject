from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260320_0001"
down_revision = None
branch_labels = None
depends_on = None


site_status = sa.Enum("running", "stopped", "building", "error", name="site_status")
task_status = sa.Enum("queued", "running", "success", "failed", "canceled", name="task_status")
task_type = sa.Enum(
    "develop_code",
    "test_local_playwright",
    "deploy_local",
    "deploy_apollo",
    name="task_type",
)
plan_tier = sa.Enum("free", "pro", "enterprise", name="plan_tier")
user_role = sa.Enum("owner", "admin", "developer", "viewer", name="user_role")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        site_status.create(bind, checkfirst=True)
        task_status.create(bind, checkfirst=True)
        task_type.create(bind, checkfirst=True)
        plan_tier.create(bind, checkfirst=True)
        user_role.create(bind, checkfirst=True)

    op.create_table(
        "app_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("llm_mode", sa.String(length=50), nullable=True),
        sa.Column("llm_base_url", sa.String(length=500), nullable=True),
        sa.Column("llm_api_key", sa.String(length=500), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("codex_client_id", sa.String(length=255), nullable=True),
        sa.Column("codex_client_secret", sa.String(length=255), nullable=True),
        sa.Column("codex_redirect_uri", sa.String(length=500), nullable=True),
        sa.Column("codex_access_token", sa.String(length=1000), nullable=True),
        sa.Column("codex_mcp_url", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("plan_tier", plan_tier, nullable=False, server_default="free"),
        sa.Column("ai_quota_monthly", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("default_org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["default_org_id"], ["organizations.id"], name="fk_users_default_org_id_organizations"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_table(
        "organization_members",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="developer"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_organization_members_org_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_organization_members_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "user_id", name="pk_organization_members"),
    )
    op.create_table(
        "templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.String(length=500), nullable=True),
        sa.Column("code_archive_url", sa.String(length=500), nullable=True),
        sa.Column("tech_stack", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rating", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_templates_created_by_users"),
        sa.UniqueConstraint("slug", name="uq_templates_slug"),
    )
    op.create_index("ix_templates_slug", "templates", ["slug"], unique=False)
    op.create_table(
        "sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("site_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", site_status, nullable=False, server_default="stopped"),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("root_path", sa.Text(), nullable=True),
        sa.Column("preview_url", sa.String(length=500), nullable=True),
        sa.Column("internal_url", sa.String(length=500), nullable=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_sites_org_id_organizations"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_sites_owner_id_users"),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], name="fk_sites_template_id_templates"),
        sa.UniqueConstraint("port", name="uq_sites_port"),
        sa.UniqueConstraint("site_id", name="uq_sites_site_id"),
    )
    op.create_index("ix_sites_org_id", "sites", ["org_id"], unique=False)
    op.create_index("ix_sites_owner_id", "sites", ["owner_id"], unique=False)
    op.create_index("ix_sites_site_id", "sites", ["site_id"], unique=False)
    op.create_table(
        "site_deploy_configs",
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False, server_default="local"),
        sa.Column("system_api_base", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("system_id", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("app_id", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("harbor_domain", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("harbor_domain_public", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("harbor_namespace", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("module_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("login_tel", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("login_password", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("login_random", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("login_path", sa.String(length=255), nullable=False, server_default="/apollo/user/login"),
        sa.Column("deploy_path", sa.String(length=255), nullable=False, server_default="/devops/cicd/v1.0/job/deployByImage"),
        sa.Column("extra_headers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name="fk_site_deploy_configs_site_id_sites", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("site_id", name="pk_site_deploy_configs"),
    )
    op.create_table(
        "site_provider_configs",
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("codex_cmd", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("claude_cmd", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("gemini_cmd", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("codex_auth_cmd", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("claude_auth_cmd", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("gemini_auth_cmd", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name="fk_site_provider_configs_site_id_sites", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("site_id", name="pk_site_provider_configs"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_type", task_type, nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("status", task_status, nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("queue_name", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_tasks_created_by_users"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name="fk_tasks_site_id_sites", ondelete="CASCADE"),
    )
    op.create_index("ix_tasks_celery_task_id", "tasks", ["celery_task_id"], unique=False)
    op.create_index("ix_tasks_site_id", "tasks", ["site_id"], unique=False)
    op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)
    op.create_table(
        "task_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False, server_default="INFO"),
        sa.Column("line", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_task_logs_task_id_tasks", ondelete="CASCADE"),
    )
    op.create_index("ix_task_logs_task_id", "task_logs", ["task_id"], unique=False)
    op.create_table(
        "site_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("snapshot_url", sa.String(length=500), nullable=True),
        sa.Column("commit_message", sa.Text(), nullable=True),
        sa.Column("diff_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deployed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_site_versions_created_by_users"),
        sa.ForeignKeyConstraint(["parent_version_id"], ["site_versions.id"], name="fk_site_versions_parent_version_id_site_versions"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name="fk_site_versions_site_id_sites", ondelete="CASCADE"),
        sa.UniqueConstraint("site_id", "version_number", name="uq_site_version"),
    )


def downgrade() -> None:
    op.drop_table("site_versions")
    op.drop_index("ix_task_logs_task_id", table_name="task_logs")
    op.drop_table("task_logs")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_site_id", table_name="tasks")
    op.drop_index("ix_tasks_celery_task_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("site_provider_configs")
    op.drop_table("site_deploy_configs")
    op.drop_index("ix_sites_site_id", table_name="sites")
    op.drop_index("ix_sites_owner_id", table_name="sites")
    op.drop_index("ix_sites_org_id", table_name="sites")
    op.drop_table("sites")
    op.drop_index("ix_templates_slug", table_name="templates")
    op.drop_table("templates")
    op.drop_table("organization_members")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
    op.drop_table("app_config")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        user_role.drop(bind, checkfirst=True)
        plan_tier.drop(bind, checkfirst=True)
        task_type.drop(bind, checkfirst=True)
        task_status.drop(bind, checkfirst=True)
        site_status.drop(bind, checkfirst=True)
