from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_superuser, get_current_user, get_db
from backend.services.programming_tool_service import (
    VISIBLE_TOOL_ORDER,
    ProgrammingToolSpec,
    programming_tool_service,
)
from backend.services.programming_tool_update_service import programming_tool_update_service
from backend.services.project_service import project_service


router = APIRouter(prefix="/programming-tools")


@router.get("/versions")
async def list_programming_tool_versions(
    refresh: bool = Query(default=False),
    _current_user: object = Depends(get_current_superuser),
) -> dict[str, Any]:
    tools = await programming_tool_update_service.list_versions(refresh=refresh)
    return {"ok": True, "tools": tools}


@router.post("/{tool_id}/update", status_code=status.HTTP_202_ACCEPTED)
async def update_programming_tool(
    tool_id: str,
    _current_user: object = Depends(get_current_superuser),
) -> dict[str, Any]:
    return await programming_tool_update_service.start_update(tool_id)


def _serialize_tool(
    *,
    spec: ProgrammingToolSpec,
    resolved: tuple[Any, str] | None,
    health_result: tuple[bool, dict[str, Any]],
) -> dict[str, Any]:
    healthy, health = health_result
    provider = resolved[0] if resolved else None
    selected_format = resolved[1] if resolved else None
    configured = provider is not None
    if not configured:
        unavailable_reason = "未启用兼容的全局或项目级模型 Provider"
    elif not healthy:
        unavailable_reason = "编程工具适配器不可用"
    else:
        unavailable_reason = ""
    return {
        "id": spec.id,
        "label": spec.label,
        "available": configured and healthy,
        "configured": configured,
        "healthy": healthy,
        "unavailable_reason": unavailable_reason,
        "supported_formats": list(spec.supported_formats),
        "selected_format": selected_format,
        "provider_id": str(provider.id) if provider else None,
        "provider_name": provider.name if provider else None,
        "provider_scope": str(provider.scope_type or "global") if provider else None,
        "model": programming_tool_service.provider_model(provider) if provider else None,
        "branch_prefix": spec.branch_prefix,
        "supports_mcp": spec.supports_mcp,
        "version": str(health.get("version")) if health.get("version") else None,
    }


@router.get("")
async def list_programming_tools(
    project_id: str = Query(min_length=1),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await project_service.get_project(db, project_id, current_user)
    user_id = str(getattr(current_user, "id"))
    specs = [
        programming_tool_service.get_spec(tool_id)
        for tool_id in VISIBLE_TOOL_ORDER
    ]
    visible_specs = [spec for spec in specs if spec is not None and spec.visible]
    resolved_providers = []
    for spec in visible_specs:
        resolved_providers.append(
            await programming_tool_service.resolve_project_provider(
                db,
                user_id=user_id,
                project_id=project_id,
                tool_id=spec.id,
            )
        )
    health_results = await asyncio.gather(
        *(programming_tool_service.adapter_health(spec.id) for spec in visible_specs)
    )
    tools = [
        _serialize_tool(
            spec=spec,
            resolved=resolved,
            health_result=health,
        )
        for spec, resolved, health in zip(visible_specs, resolved_providers, health_results, strict=True)
    ]
    return {"ok": True, "tools": tools}
