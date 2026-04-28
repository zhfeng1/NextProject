from __future__ import annotations

import shutil
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import UserMcpService


BUILTIN_MCP_SERVICES: dict[str, dict[str, Any]] = {
    "context7": {
        "name": "Context7",
        "description": "文档检索与代码示例能力。",
        "required_fields": [],
        "supports_config": False,
    },
    "open-websearch": {
        "name": "Open WebSearch",
        "description": "网页搜索与最近信息检索能力。",
        "required_fields": [],
        "supports_config": False,
    },
    "spec-workflow": {
        "name": "Spec Workflow",
        "description": "规格生成与结构化文档辅助能力。",
        "required_fields": [],
        "supports_config": False,
    },
    "deepwiki": {
        "name": "DeepWiki",
        "description": "仓库/知识库型上下文检索能力。",
        "required_fields": [],
        "supports_config": False,
    },
    "playwright": {
        "name": "Playwright",
        "description": "浏览器自动化和页面交互能力。",
        "required_fields": [],
        "supports_config": False,
    },
    "exa": {
        "name": "Exa",
        "description": "高级搜索能力，启用时需要配置 API Key。",
        "required_fields": ["api_key"],
        "supports_config": True,
    },
}


class McpServiceManager:
    def _get_builtin(self, service_id: str) -> dict[str, Any]:
        builtin = BUILTIN_MCP_SERVICES.get(service_id)
        if builtin is None:
            raise HTTPException(status_code=404, detail=f"Unknown MCP service: {service_id}")
        return builtin

    async def _get_record(self, db: AsyncSession, user_id: str, service_id: str) -> UserMcpService | None:
        rows = await db.execute(
            select(UserMcpService).where(
                UserMcpService.user_id == user_id,
                UserMcpService.service_id == service_id,
            )
        )
        return rows.scalars().first()

    def _validate(self, service_id: str, enabled: bool, config: dict[str, Any]) -> None:
        builtin = self._get_builtin(service_id)
        missing = [field for field in builtin["required_fields"] if enabled and not str(config.get(field) or "").strip()]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required config fields: {', '.join(missing)}")

    def _serialize(self, builtin_id: str, record: UserMcpService | None) -> dict[str, Any]:
        builtin = self._get_builtin(builtin_id)
        config = dict(getattr(record, "config_json", None) or {})
        return {
            "service_id": builtin_id,
            "name": builtin["name"],
            "description": builtin["description"],
            "required_fields": list(builtin["required_fields"]),
            "supports_config": bool(builtin["supports_config"]),
            "enabled": bool(getattr(record, "enabled", False)),
            "config": config,
            "last_test_ok": getattr(record, "last_test_ok", None),
            "last_tested_at": getattr(record, "last_tested_at", None).isoformat() if getattr(record, "last_tested_at", None) else None,
            "last_error": getattr(record, "last_error", ""),
        }

    async def list_services(self, db: AsyncSession, current_user: object) -> list[dict[str, Any]]:
        user_id = str(getattr(current_user, "id"))
        rows = await db.execute(select(UserMcpService).where(UserMcpService.user_id == user_id))
        records = {row.service_id: row for row in rows.scalars().all()}
        return [self._serialize(service_id, records.get(service_id)) for service_id in BUILTIN_MCP_SERVICES]

    async def update_service(
        self,
        db: AsyncSession,
        current_user: object,
        service_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        user_id = str(getattr(current_user, "id"))
        config = dict(payload.get("config") or {})
        enabled = bool(payload.get("enabled", False))
        self._validate(service_id, enabled, config)
        record = await self._get_record(db, user_id, service_id)
        if record is None:
            record = UserMcpService(user_id=user_id, service_id=service_id)
            db.add(record)
        record.enabled = enabled
        record.config_json = config
        record.last_error = ""
        await db.commit()
        await db.refresh(record)
        return self._serialize(service_id, record)

    async def test_service(self, db: AsyncSession, current_user: object, service_id: str) -> dict[str, Any]:
        user_id = str(getattr(current_user, "id"))
        builtin = self._get_builtin(service_id)
        record = await self._get_record(db, user_id, service_id)
        config = dict(getattr(record, "config_json", None) or {})
        enabled = bool(getattr(record, "enabled", False))

        ok = True
        message = "配置有效"
        if not enabled:
            ok = False
            message = "服务尚未启用"
        elif builtin["required_fields"]:
            missing = [field for field in builtin["required_fields"] if not str(config.get(field) or "").strip()]
            if missing:
                ok = False
                message = f"缺少必填配置: {', '.join(missing)}"
        elif service_id == "playwright":
            ok = shutil.which("node") is not None
            message = "Node.js 可用" if ok else "Node.js 不可用"

        now = datetime.now(timezone.utc)
        if record is None:
            record = UserMcpService(user_id=user_id, service_id=service_id, enabled=enabled, config_json=config)
            db.add(record)
        record.last_test_ok = ok
        record.last_tested_at = now
        record.last_error = "" if ok else message
        await db.commit()
        await db.refresh(record)
        return {
            "ok": ok,
            "message": message,
            "service": self._serialize(service_id, record),
        }

    async def get_enabled_services(
        self,
        db: AsyncSession,
        user_id: str,
        service_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        rows = await db.execute(select(UserMcpService).where(UserMcpService.user_id == user_id, UserMcpService.enabled.is_(True)))
        enabled_records = {row.service_id: row for row in rows.scalars().all()}
        picked_ids = service_ids or list(enabled_records.keys())
        services: list[dict[str, Any]] = []
        for service_id in picked_ids:
            if service_id not in BUILTIN_MCP_SERVICES:
                continue
            record = enabled_records.get(service_id)
            if record is None and service_ids:
                continue
            services.append(self._serialize(service_id, record))
        return services


mcp_service = McpServiceManager()
