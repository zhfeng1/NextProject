from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path("/shared")
GENERATED_SITES_ROOT = Path("/generated_sites")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "NextProject"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str = Field(
        default="sqlite+aiosqlite:////shared/app_v2.db",
        alias="DATABASE_URL",
    )
    sync_database_url: str | None = Field(default=None, alias="SYNC_DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND")

    secret_key: str = Field(alias="SECRET_KEY")
    fernet_key: str = Field(alias="FERNET_KEY")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    minio_endpoint: str = Field(default="localhost:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin2025", alias="MINIO_SECRET_KEY")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")
    minio_bucket_templates: str = "site-templates"
    minio_bucket_versions: str = "site-versions"
    cors_allow_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:18080,http://127.0.0.1:18080",
        alias="CORS_ALLOW_ORIGINS",
    )
    cors_allow_credentials: bool = Field(default=True, alias="CORS_ALLOW_CREDENTIALS")
    cors_allow_methods: str = Field(default="*", alias="CORS_ALLOW_METHODS")
    cors_allow_headers: str = Field(default="*", alias="CORS_ALLOW_HEADERS")

    code_mcp_bridge_url: str = Field(default="http://codex-mcp:8090", alias="CODEX_MCP_BRIDGE_URL")
    llm_dialog_log_enabled: bool = Field(default=False, alias="LLM_DIALOG_LOG_ENABLED")
    llm_dialog_log_max_chars: int = Field(default=4000, alias="LLM_DIALOG_LOG_MAX_CHARS")

    sub_site_port_start: int = Field(default=19100, alias="SUB_SITE_PORT_START")
    sub_site_port_end: int = Field(default=19999, alias="SUB_SITE_PORT_END")

    codex_cmd: str = Field(default="codex", alias="CODEX_CMD")
    claude_cmd: str = Field(default="claude", alias="CLAUDE_CMD")
    gemini_cmd: str = Field(default="gemini", alias="GEMINI_CMD")
    codex_auth_cmd: str = Field(default="codex login --device-auth", alias="CODEX_AUTH_CMD")
    claude_auth_cmd: str = Field(default="claude login", alias="CLAUDE_AUTH_CMD")
    gemini_auth_cmd: str = Field(default="gemini auth login", alias="GEMINI_AUTH_CMD")

    playwright_base_url: str = Field(default="http://127.0.0.1:8080", alias="PLAYWRIGHT_BASE_URL")
    default_task_timeout_seconds: int = 1800
    enable_internal_task_fallback: bool = True
    create_tables_on_startup: bool = True
    default_template_count: int = 5
    legacy_api_prefix: str = "/api"
    api_prefix: str = "/api"
    api_version_prefix: str = "/api/v2"
    metrics_path: str = "/metrics"

    provider_list: tuple[str, ...] = ("codex", "claude_code", "gemini_cli")
    supported_task_types: tuple[str, ...] = (
        "develop_code",
        "test_local_playwright",
        "deploy_local",
        "deploy_apollo",
    )
    default_org_slug: str = "default-org"
    default_org_name: str = "Default Organization"
    default_admin_email: str = Field(default="admin@example.com", alias="DEFAULT_ADMIN_EMAIL")
    default_admin_password: str = Field(default="admin123456", alias="DEFAULT_ADMIN_PASSWORD")
    default_site_tech_stack_backend: Literal["fastapi"] = "fastapi"
    default_site_tech_stack_frontend: Literal["vue3"] = "vue3"

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        value = value.strip()
        if not value or value == "change-me-in-production":
            raise ValueError(
                "SECRET_KEY must be set to a secure non-default value. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        if len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return value

    @field_validator("fernet_key")
    @classmethod
    def validate_fernet_key(cls, value: str) -> str:
        value = value.strip()
        if not value or value == "replace-with-fernet-key":
            raise ValueError(
                "FERNET_KEY must be set. "
                'Generate one with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        if len(value) != 44:
            raise ValueError("FERNET_KEY must be a valid Fernet key (44 characters, base64 encoded)")
        return value

    @field_validator("default_admin_password")
    @classmethod
    def validate_default_admin_password(cls, value: str, info) -> str:
        value = value.strip()
        insecure_defaults = {"admin123456", "admin", "password", "123456"}
        if value in insecure_defaults:
            import warnings
            warnings.warn(
                "DEFAULT_ADMIN_PASSWORD is set to a well-known insecure default. "
                "Change it via the DEFAULT_ADMIN_PASSWORD environment variable before deploying to production.",
                stacklevel=2,
            )
        if len(value) < 8:
            raise ValueError("DEFAULT_ADMIN_PASSWORD must be at least 8 characters long")
        return value

    @staticmethod
    def _split_csv(value: str) -> tuple[str, ...]:
        return tuple(item.strip() for item in value.split(",") if item.strip())

    @property
    def cors_allow_origins_list(self) -> tuple[str, ...]:
        return self._split_csv(self.cors_allow_origins)

    @property
    def cors_allow_methods_list(self) -> tuple[str, ...]:
        return self._split_csv(self.cors_allow_methods)

    @property
    def cors_allow_headers_list(self) -> tuple[str, ...]:
        return self._split_csv(self.cors_allow_headers)

    @property
    def resolved_sync_database_url(self) -> str:
        if self.sync_database_url:
            return self.sync_database_url
        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        if self.database_url.startswith("sqlite+aiosqlite:///"):
            return self.database_url.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
