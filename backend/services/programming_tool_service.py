from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.encryption import decrypt_api_key
from backend.models.user_llm_provider import UserLLMProvider


SUPPORTED_FORMATS = ("responses", "messages", "chat_completions")
FORMAT_PRIORITY = SUPPORTED_FORMATS
VISIBLE_TOOL_ORDER = ("codex", "codebuddy", "opencode", "kimi_code")


@dataclass(frozen=True, slots=True)
class ProgrammingToolSpec:
    id: str
    label: str
    adapter_url: str
    supported_formats: tuple[str, ...]
    branch_prefix: str
    visible: bool = True
    supports_mcp: bool = True


class ProgrammingToolService:
    def __init__(self) -> None:
        settings = get_settings()
        self._adapter_token = settings.programming_tool_adapter_token
        self._specs = {
            "codex": ProgrammingToolSpec(
                id="codex",
                label="Codex",
                adapter_url=settings.codex_adapter_url.rstrip("/"),
                supported_formats=("responses",),
                branch_prefix="codex/",
            ),
            "claude_code": ProgrammingToolSpec(
                id="claude_code",
                label="Claude Code",
                adapter_url=settings.claude_code_adapter_url.rstrip("/"),
                supported_formats=("messages",),
                branch_prefix="claude-code/",
                visible=False,
            ),
            "codebuddy": ProgrammingToolSpec(
                id="codebuddy",
                label="CodeBuddy",
                adapter_url=settings.codebuddy_adapter_url.rstrip("/"),
                supported_formats=SUPPORTED_FORMATS,
                branch_prefix="codebuddy/",
            ),
            "opencode": ProgrammingToolSpec(
                id="opencode",
                label="OpenCode",
                adapter_url=settings.opencode_adapter_url.rstrip("/"),
                supported_formats=SUPPORTED_FORMATS,
                branch_prefix="opencode/",
            ),
            "kimi_code": ProgrammingToolSpec(
                id="kimi_code",
                label="Kimi Code",
                adapter_url=settings.kimi_code_adapter_url.rstrip("/"),
                supported_formats=SUPPORTED_FORMATS,
                branch_prefix="kimi-code/",
            ),
        }

    def tool_ids(self, *, include_hidden: bool = True) -> set[str]:
        if include_hidden:
            return set(self._specs)
        return {tool_id for tool_id, spec in self._specs.items() if spec.visible}

    def label(self, tool_id: str) -> str:
        spec = self._specs.get(tool_id)
        return spec.label if spec else "编程工具"

    def get_spec(self, tool_id: str) -> ProgrammingToolSpec | None:
        return self._specs.get(tool_id)

    @staticmethod
    def provider_formats(provider: UserLLMProvider) -> list[str]:
        raw = getattr(provider, "formats_json", None) or []
        if isinstance(raw, str):
            raw = [raw]
        formats = [str(item).strip() for item in raw if str(item).strip() in SUPPORTED_FORMATS]
        legacy = str(getattr(provider, "format", "") or "").strip()
        if legacy in SUPPORTED_FORMATS and legacy not in formats:
            formats.insert(0, legacy)
        if not formats:
            formats = ["responses"]
        return list(dict.fromkeys(formats))

    @classmethod
    def provider_enabled_formats(cls, provider: UserLLMProvider) -> list[str]:
        raw = getattr(provider, "enabled_formats_json", None) or []
        if isinstance(raw, str):
            raw = [raw]
        supported = set(cls.provider_formats(provider))
        enabled = [str(item).strip() for item in raw if str(item).strip() in supported]
        return list(dict.fromkeys(enabled))

    @staticmethod
    def provider_model(provider: UserLLMProvider) -> str:
        models = provider.models or []
        if isinstance(models, str):
            models = [models]
        return next((str(item).strip() for item in models if str(item).strip()), "")

    @classmethod
    def provider_is_configured(cls, provider: UserLLMProvider) -> bool:
        return bool(decrypt_api_key(provider.api_key) and cls.provider_model(provider))

    async def _providers_for_scope(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        scope_type: str,
        project_id: str | None = None,
    ) -> list[UserLLMProvider]:
        query = select(UserLLMProvider).where(
            UserLLMProvider.user_id == str(user_id),
            UserLLMProvider.scope_type == scope_type,
        )
        if scope_type == "project":
            query = query.where(UserLLMProvider.project_id == str(project_id or ""))
        else:
            query = query.where(UserLLMProvider.project_id.is_(None))
        rows = await db.execute(
            query.order_by(UserLLMProvider.is_default.desc(), UserLLMProvider.created_at, UserLLMProvider.id)
        )
        return list(rows.scalars().all())

    async def resolve_project_provider(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        project_id: str,
        tool_id: str,
    ) -> tuple[UserLLMProvider, str] | None:
        spec = self.get_spec(tool_id)
        if spec is None or not project_id:
            return None
        project_providers = await self._providers_for_scope(
            db,
            user_id=str(user_id),
            scope_type="project",
            project_id=str(project_id),
        )
        global_providers = await self._providers_for_scope(
            db,
            user_id=str(user_id),
            scope_type="global",
        )
        supported = set(spec.supported_formats)
        # Project-scoped providers override global defaults. Within each scope,
        # retain the fixed protocol priority.
        for providers in (project_providers, global_providers):
            for fmt in FORMAT_PRIORITY:
                if fmt not in supported:
                    continue
                for provider in providers:
                    if fmt not in self.provider_enabled_formats(provider):
                        continue
                    if not self.provider_is_configured(provider):
                        continue
                    if spec.id in {"codebuddy", "opencode", "kimi_code"} and not str(provider.base_url or "").strip():
                        continue
                    return provider, fmt
        return None

    async def require_project_provider(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        project_id: str,
        tool_id: str,
    ) -> tuple[UserLLMProvider, str]:
        spec = self.get_spec(tool_id)
        if spec is None:
            raise HTTPException(status_code=400, detail="不支持的编程工具")
        resolved = await self.resolve_project_provider(
            db,
            user_id=user_id,
            project_id=project_id,
            tool_id=tool_id,
        )
        if resolved is None:
            formats = "、".join(spec.supported_formats)
            required_fields = "API Key、Base URL 和模型" if spec.id in {"codebuddy", "opencode", "kimi_code"} else "API Key 和模型"
            raise HTTPException(
                status_code=400,
                detail=f"请先启用可用的全局或项目级 {spec.label} Provider（支持格式：{formats}，并填写 {required_fields}）",
            )
        return resolved

    async def adapter_health(self, tool_id: str) -> tuple[bool, dict[str, Any]]:
        spec = self.get_spec(tool_id)
        if spec is None or not spec.adapter_url:
            return False, {}
        headers: dict[str, str] = {}
        if self._adapter_token:
            headers["X-Adapter-Token"] = self._adapter_token
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                response = await client.get(f"{spec.adapter_url}/health", headers=headers)
                response.raise_for_status()
                payload = response.json()
                healthy = bool(payload.get("ok", True)) and bool(payload.get("cli_available", True))
                return healthy, payload
        except (httpx.HTTPError, ValueError):
            return False, {}


programming_tool_service = ProgrammingToolService()
SUPPORTED_TOOL_IDS = frozenset(programming_tool_service.tool_ids())
