from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.schemas.tech_platform import (
    TechPlatformModuleCreate,
    TechPlatformModuleUpdate,
    TechPlatformPreviewRequest,
    TechPlatformValidateRequest,
)
from backend.services.task_service import task_service
from backend.services.tech_platform_deploy_service import tech_platform_deploy_service


router = APIRouter(prefix="/projects")


@router.get("/{project_id}/tech-platform/modules")
async def list_tech_platform_modules(
    project_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    modules = await tech_platform_deploy_service.list_modules(
        db, project_id, current_user
    )
    return {"ok": True, "modules": modules}


@router.post("/{project_id}/tech-platform/modules/scan")
async def scan_tech_platform_modules(
    project_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    modules = await tech_platform_deploy_service.scan_modules(
        db, project_id, current_user
    )
    return {"ok": True, "modules": modules}


@router.post("/{project_id}/tech-platform/modules")
async def create_tech_platform_module(
    project_id: str,
    payload: TechPlatformModuleCreate,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    module = await tech_platform_deploy_service.create_module(
        db, project_id, payload, current_user
    )
    return {"ok": True, "module": module}


@router.patch("/{project_id}/tech-platform/modules/{module_id}")
async def update_tech_platform_module(
    project_id: str,
    module_id: str,
    payload: TechPlatformModuleUpdate,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    module = await tech_platform_deploy_service.update_module(
        db, project_id, module_id, payload, current_user
    )
    return {"ok": True, "module": module}


@router.delete("/{project_id}/tech-platform/modules/{module_id}")
async def delete_tech_platform_module(
    project_id: str,
    module_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await tech_platform_deploy_service.delete_module(
        db, project_id, module_id, current_user
    )
    return {"ok": True}


@router.post("/{project_id}/tech-platform/modules/{module_id}/preview")
async def preview_tech_platform_module(
    project_id: str,
    module_id: str,
    payload: TechPlatformPreviewRequest,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    preview = await tech_platform_deploy_service.preview_module(
        db, project_id, module_id, current_user, payload.image or ""
    )
    return {"ok": True, **preview}


@router.post("/{project_id}/tech-platform/modules/{module_id}/validate")
async def validate_tech_platform_module(
    project_id: str,
    module_id: str,
    payload: TechPlatformValidateRequest,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await tech_platform_deploy_service.validate_module(
        db, project_id, module_id, current_user, payload.image or ""
    )
    return {"ok": True, **result}


@router.post("/{project_id}/tech-platform/modules/{module_id}/deploy")
async def deploy_tech_platform_module(
    project_id: str,
    module_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await tech_platform_deploy_service.create_deploy_task(
        db, project_id, module_id, current_user
    )
    return {
        "ok": True,
        "task_id": str(task.id),
        "task": task_service.serialize_task(task),
    }
