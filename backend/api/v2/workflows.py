from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.workflow_service import workflow_service

router = APIRouter(prefix="/workflows")


@router.get("/runs")
async def list_workflow_runs(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"ok": True, "runs": await workflow_service.list_runs(db, current_user, limit=limit)}


@router.get("/sites/{site_id}/current")
async def get_current_workflow_run(
    site_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"ok": True, "run": await workflow_service.get_current_run(db, current_user, site_id)}


@router.post("/sites/{site_id}/runs")
async def create_workflow_run(
    site_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"ok": True, "run": await workflow_service.create_run(db, current_user, site_id, payload)}


@router.get("/runs/{run_id}")
async def get_workflow_run(
    run_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"ok": True, "run": await workflow_service.get_run_detail(db, current_user, run_id)}


@router.post("/runs/{run_id}/generate-stage")
async def generate_workflow_stage(
    run_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await workflow_service.generate_stage(db, current_user, run_id, payload)


@router.post("/runs/{run_id}/confirm-stage")
async def confirm_workflow_stage(
    run_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await workflow_service.confirm_stage(db, current_user, run_id)


@router.get("/runs/{run_id}/artifacts")
async def get_workflow_artifacts(
    run_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await workflow_service.get_artifacts(db, current_user, run_id)
