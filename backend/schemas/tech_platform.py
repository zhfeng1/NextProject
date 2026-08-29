from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class TechPlatformModuleCreate(BaseModel):
    site_id: str = Field(min_length=1, max_length=64)
    dockerfile_path: str = Field(min_length=1, max_length=512)
    build_context: str | None = Field(default=None, max_length=512)
    app_name: str | None = Field(default=None, max_length=255)
    namespace: str | None = Field(default=None, max_length=255)
    harbor_project: str | None = Field(default=None, max_length=255)
    repository_name: str | None = Field(default=None, max_length=255)
    app_type: str = Field(default="2", min_length=1, max_length=16)
    container_port: int = Field(default=8080, ge=1, le=65535)
    service_port: int = Field(default=80, ge=1, le=65535)
    config_map_template: str | None = None
    deployment_template: str | None = None
    service_template: str | None = None

    @field_validator("site_id", "dockerfile_path", mode="before")
    @classmethod
    def strip_required_strings(cls, value: object) -> str:
        return str(value or "").strip()


class TechPlatformModuleUpdate(BaseModel):
    dockerfile_path: str | None = Field(default=None, min_length=1, max_length=512)
    build_context: str | None = Field(default=None, min_length=1, max_length=512)
    app_name: str | None = Field(default=None, min_length=1, max_length=255)
    namespace: str | None = Field(default=None, min_length=1, max_length=255)
    harbor_project: str | None = Field(default=None, min_length=1, max_length=255)
    repository_name: str | None = Field(default=None, min_length=1, max_length=255)
    app_type: str | None = Field(default=None, min_length=1, max_length=16)
    container_port: int | None = Field(default=None, ge=1, le=65535)
    service_port: int | None = Field(default=None, ge=1, le=65535)
    config_map_template: str | None = None
    deployment_template: str | None = None
    service_template: str | None = None

    @field_validator(
        "dockerfile_path",
        "build_context",
        "app_name",
        "namespace",
        "harbor_project",
        "repository_name",
        "app_type",
        mode="before",
    )
    @classmethod
    def strip_optional_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class TechPlatformPreviewRequest(BaseModel):
    image: str | None = Field(default=None, max_length=1024)


class TechPlatformValidateRequest(TechPlatformPreviewRequest):
    pass
