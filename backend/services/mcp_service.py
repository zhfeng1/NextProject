from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import McpServiceConfig, Site
from backend.services.site_service import site_service


BUILTIN_MCP_SERVICES: dict[str, dict[str, Any]] = {
    "context7": {
        "name": "Context7",
        "description": "文档检索与代码示例能力。",
        "required_fields": [],
        "supports_config": False,
        "config": {"command": "npx", "args": ["-y", "@upstash/context7-mcp"]},
    },
    "open-websearch": {
        "name": "Open WebSearch",
        "description": "网页搜索与最近信息检索能力。",
        "required_fields": [],
        "supports_config": False,
        "config": {},
    },
    "spec-workflow": {
        "name": "Spec Workflow",
        "description": "规格生成与结构化文档辅助能力。",
        "required_fields": [],
        "supports_config": False,
        "config": {},
    },
    "deepwiki": {
        "name": "DeepWiki",
        "description": "仓库/知识库型上下文检索能力。",
        "required_fields": [],
        "supports_config": False,
        "config": {},
    },
    "playwright": {
        "name": "Playwright",
        "description": "浏览器自动化和页面交互能力。",
        "required_fields": [],
        "supports_config": False,
        "config": {"command": "npx", "args": ["-y", "@playwright/mcp"]},
    },
    "exa": {
        "name": "Exa",
        "description": "高级搜索能力，启用时需要配置 API Key。",
        "required_fields": ["api_key"],
        "supports_config": True,
        "config": {"command": "npx", "args": ["-y", "exa-mcp-server"]},
    },
}

SCOPE_PRIORITY = {"global": 1, "project": 2, "repo": 3}


class McpServiceManager:
    def _builtin(self, service_id: str) -> dict[str, Any]:
        return BUILTIN_MCP_SERVICES.get(service_id, {
            "name": service_id,
            "description": "",
            "required_fields": [],
            "supports_config": True,
            "config": {},
        })

    async def _resolve_site_db_id(self, db: AsyncSession, current_user: object, site_id: str | None) -> str | None:
        if not site_id:
            return None
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        return str(site.id)

    def _validate_scope(self, scope_type: str, project_id: str | None, site_db_id: str | None) -> None:
        if scope_type not in SCOPE_PRIORITY:
            raise HTTPException(status_code=400, detail="scope_type must be global, project, or repo")
        if scope_type == "global" and (project_id or site_db_id):
            raise HTTPException(status_code=400, detail="global scope cannot include project_id or site_id")
        if scope_type == "project" and not project_id:
            raise HTTPException(status_code=400, detail="project scope requires project_id")
        if scope_type == "repo" and not site_db_id:
            raise HTTPException(status_code=400, detail="repo scope requires site_id")

    def _validate_config(self, required_fields: list[str], enabled: bool, config: dict[str, Any]) -> None:
        missing = [field for field in required_fields if enabled and not str(config.get(field) or "").strip()]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required config fields: {', '.join(missing)}")

    def _serialize(self, record: McpServiceConfig, *, site_public_id: str = "") -> dict[str, Any]:
        return {
            "id": str(record.id),
            "service_id": record.service_id,
            "name": record.name,
            "description": record.description,
            "scope_type": record.scope_type,
            "project_id": str(record.project_id) if record.project_id else "",
            "site_id": site_public_id or (str(record.site_id) if record.site_id else ""),
            "enabled": bool(record.enabled),
            "config": dict(record.config_json or {}),
            "required_fields": list(record.required_fields_json or []),
            "supports_config": bool(record.supports_config),
            "last_test_ok": record.last_test_ok,
            "last_tested_at": record.last_tested_at.isoformat() if record.last_tested_at else None,
            "last_error": record.last_error,
        }

    async def list_services(
        self,
        db: AsyncSession,
        current_user: object,
        *,
        project_id: str | None = None,
        site_id: str | None = None,
        scope_type: str | None = None,
    ) -> list[dict[str, Any]]:
        site_db_id = await self._resolve_site_db_id(db, current_user, site_id)
        query = select(McpServiceConfig)
        if scope_type:
            query = query.where(McpServiceConfig.scope_type == scope_type)
        if project_id:
            query = query.where(McpServiceConfig.project_id == project_id)
        if site_db_id:
            query = query.where(McpServiceConfig.site_id == site_db_id)
        rows = list((await db.execute(query.order_by(McpServiceConfig.scope_type, McpServiceConfig.service_id))).scalars().all())
        site_map = await self._site_public_map(db, [str(row.site_id) for row in rows if row.site_id])
        services = [self._serialize(row, site_public_id=site_map.get(str(row.site_id), "")) for row in rows]
        if not project_id and not site_id and not scope_type:
            existing = {(item["service_id"], item["scope_type"], item["project_id"], item["site_id"]) for item in services}
            for service_id, builtin in BUILTIN_MCP_SERVICES.items():
                key = (service_id, "global", "", "")
                if key not in existing:
                    services.append({
                        "id": "",
                        "service_id": service_id,
                        "name": builtin["name"],
                        "description": builtin["description"],
                        "scope_type": "global",
                        "project_id": "",
                        "site_id": "",
                        "enabled": False,
                        "config": dict(builtin.get("config") or {}),
                        "required_fields": list(builtin["required_fields"]),
                        "supports_config": bool(builtin["supports_config"]),
                        "last_test_ok": None,
                        "last_tested_at": None,
                        "last_error": "",
                    })
        return services

    async def _site_public_map(self, db: AsyncSession, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        rows = await db.execute(select(Site).where(Site.id.in_(ids)))
        return {str(site.id): site.site_id for site in rows.scalars().all()}

    async def update_service(
        self,
        db: AsyncSession,
        current_user: object,
        service_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        builtin = self._builtin(service_id)
        scope_type = str(payload.get("scope_type") or "global").strip() or "global"
        project_id = str(payload.get("project_id") or "").strip() or None
        site_public_id = str(payload.get("site_id") or "").strip() or None
        site_db_id = await self._resolve_site_db_id(db, current_user, site_public_id)
        if scope_type != "project":
            project_id = None
        if scope_type != "repo":
            site_db_id = None
            site_public_id = None
        self._validate_scope(scope_type, project_id, site_db_id)

        config = dict(payload.get("config") or builtin.get("config") or {})
        enabled = bool(payload.get("enabled", True))
        required_fields = list(payload.get("required_fields") or builtin["required_fields"])
        self._validate_config(required_fields, enabled, config)

        query = select(McpServiceConfig).where(
            McpServiceConfig.service_id == service_id,
            McpServiceConfig.scope_type == scope_type,
        )
        if scope_type == "global":
            query = query.where(McpServiceConfig.project_id.is_(None), McpServiceConfig.site_id.is_(None))
        elif scope_type == "project":
            query = query.where(McpServiceConfig.project_id == project_id)
        else:
            query = query.where(McpServiceConfig.site_id == site_db_id)
        record = (await db.execute(query)).scalars().first()
        if record is None:
            record = McpServiceConfig(
                id=str(uuid.uuid4()),
                service_id=service_id,
                scope_type=scope_type,
                project_id=project_id,
                site_id=site_db_id,
            )
            db.add(record)
        record.name = str(payload.get("name") or builtin["name"]).strip() or service_id
        record.description = str(payload.get("description") or builtin["description"]).strip()
        record.enabled = enabled
        record.config_json = config
        record.required_fields_json = required_fields
        record.supports_config = bool(payload.get("supports_config", builtin["supports_config"]))
        record.last_error = ""
        await db.commit()
        await db.refresh(record)
        return self._serialize(record, site_public_id=site_public_id or "")

    async def test_service(self, db: AsyncSession, current_user: object, service_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        scope_type = str(payload.get("scope_type") or "global").strip() or "global"
        project_id = str(payload.get("project_id") or "").strip() or None
        site_public_id = str(payload.get("site_id") or "").strip() or None
        site_db_id = await self._resolve_site_db_id(db, current_user, site_public_id)
        query = select(McpServiceConfig).where(McpServiceConfig.service_id == service_id, McpServiceConfig.scope_type == scope_type)
        if scope_type == "project":
            query = query.where(McpServiceConfig.project_id == project_id)
        elif scope_type == "repo":
            query = query.where(McpServiceConfig.site_id == site_db_id)
        else:
            query = query.where(McpServiceConfig.project_id.is_(None), McpServiceConfig.site_id.is_(None))
        record = (await db.execute(query)).scalars().first()
        if record is None:
            raise HTTPException(status_code=404, detail="MCP service config not found")
        ok = bool(record.enabled)
        message = "配置有效" if ok else "服务尚未启用"
        missing = [field for field in (record.required_fields_json or []) if not str((record.config_json or {}).get(field) or "").strip()]
        if ok and missing:
            ok = False
            message = f"缺少必填配置: {', '.join(missing)}"
        if ok and record.service_id == "playwright":
            ok = shutil.which("node") is not None
            message = "Node.js 可用" if ok else "Node.js 不可用"
        record.last_test_ok = ok
        record.last_tested_at = datetime.now(timezone.utc)
        record.last_error = "" if ok else message
        await db.commit()
        await db.refresh(record)
        return {"ok": ok, "message": message, "service": self._serialize(record, site_public_id=site_public_id or "")}

    async def resolve_for_repos(
        self,
        db: AsyncSession,
        *,
        project_id: str | None,
        site_ids: list[str],
        selected_service_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        conditions = [McpServiceConfig.scope_type == "global"]
        if project_id:
            conditions.append(McpServiceConfig.project_id == project_id)
        if site_ids:
            conditions.append(McpServiceConfig.site_id.in_(site_ids))
        rows = list((await db.execute(select(McpServiceConfig).where(or_(*conditions), McpServiceConfig.enabled.is_(True)))).scalars().all())
        selected = {item for item in (selected_service_ids or []) if item}
        effective: dict[str, McpServiceConfig] = {}
        for row in rows:
            if selected and row.service_id not in selected:
                continue
            current = effective.get(row.service_id)
            if current is None or SCOPE_PRIORITY.get(row.scope_type, 0) >= SCOPE_PRIORITY.get(current.scope_type, 0):
                effective[row.service_id] = row
        return [self._serialize(row) for row in sorted(effective.values(), key=lambda item: item.service_id)]


mcp_service = McpServiceManager()
