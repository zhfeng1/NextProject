from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, field_validator


ApiFormat = Literal["responses", "messages", "chat_completions"]


class ModelSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    api_format: ApiFormat = Field(
        validation_alias=AliasChoices("api_format", "format"),
        serialization_alias="api_format",
    )
    base_url: str = ""
    api_key: SecretStr
    model: str = ""
    provider_name: str = ""

    @field_validator("base_url", "model", "provider_name", mode="before")
    @classmethod
    def normalize_strings(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("api_key")
    @classmethod
    def require_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("api_key is required")
        return value


class McpService(BaseModel):
    model_config = ConfigDict(extra="allow")

    service_id: str
    name: str = ""
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("service_id")
    @classmethod
    def validate_service_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 100:
            raise ValueError("invalid MCP service_id")
        return normalized


class RunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    task_id: str
    conversation_id: str = ""
    native_session_id: str = Field(
        default="",
        validation_alias=AliasChoices("native_session_id", "session_id", "provider_session_id"),
        serialization_alias="native_session_id",
    )
    cwd: str
    prompt: str
    mode: str = Field(
        default="develop",
        validation_alias=AliasChoices("task_mode", "mode"),
        serialization_alias="task_mode",
    )
    model_settings: ModelSettings = Field(
        validation_alias=AliasChoices("model_config", "model_settings", "model"),
        serialization_alias="model_config",
    )
    mcp_services: list[McpService] = Field(
        default_factory=list,
        validation_alias=AliasChoices("mcp_servers", "mcp_services"),
        serialization_alias="mcp_servers",
    )
    timeout_seconds: int = Field(default=3600, ge=1, le=86_400)

    @field_validator("task_id", "conversation_id", "native_session_id", "cwd", "prompt", "mode", mode="before")
    @classmethod
    def normalize_required_strings(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        if not value or len(value) > 128:
            raise ValueError("invalid task_id")
        if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in value):
            raise ValueError("task_id contains unsupported characters")
        return value

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str) -> str:
        if not value:
            return ""
        if len(value) > 128 or any(
            ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in value
        ):
            raise ValueError("conversation_id contains unsupported characters")
        return value

    @field_validator("native_session_id")
    @classmethod
    def validate_native_session_id(cls, value: str) -> str:
        if not value:
            return ""
        if len(value) > 255 or any(
            ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for ch in value
        ):
            raise ValueError("native_session_id contains unsupported characters")
        return value

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        if not value:
            raise ValueError("prompt is required")
        return value


class ToolMetadata(BaseModel):
    tool_id: str
    name: str
    version: str
    visible: bool
    supported_formats: list[ApiFormat]
    branch_prefix: str
    supports_mcp: bool = True
    cli_available: bool = False
