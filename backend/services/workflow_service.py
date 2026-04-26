from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Site, WorkflowRun
from backend.services.site_service import site_service


WORKFLOW_STAGES = ("research", "ideate", "plan", "execute", "optimize", "review")
WORKFLOW_STAGE_LABELS = {
    "research": "研究",
    "ideate": "构思",
    "plan": "计划",
    "execute": "执行",
    "optimize": "优化",
    "review": "评审",
}


class WorkflowService:
    def _initial_stage_status(self) -> dict[str, str]:
        return {stage: ("draft" if stage == WORKFLOW_STAGES[0] else "pending") for stage in WORKFLOW_STAGES}

    def _workflow_paths(self, site_id: str, run_id: str) -> dict[str, Path]:
        np_root = site_service.np_root(site_id)
        workflows_root = np_root / "workflows"
        run_root = workflows_root / "runs" / run_id
        return {
            "root": workflows_root,
            "run_root": run_root,
            "current_file": workflows_root / "current" / f"{site_id}.json",
        }

    def _history_file(self, site_id: str, run_id: str) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return site_service.np_root(site_id) / "workflows" / "history" / f"{ts}-{run_id}.json"

    def _stage_file(self, site_id: str, run_id: str, stage: str) -> Path:
        return self._workflow_paths(site_id, run_id)["run_root"] / f"{stage}.md"

    def serialize_run(self, run: WorkflowRun, *, site: Site | None = None) -> dict[str, Any]:
        return {
            "id": str(run.id),
            "site_id": site.site_id if site else str(run.site_id),
            "site_name": getattr(site, "name", ""),
            "name": run.name,
            "status": run.status,
            "current_stage": run.current_stage,
            "current_stage_label": WORKFLOW_STAGE_LABELS.get(run.current_stage, run.current_stage),
            "stage_status": dict(run.stage_status_json or {}),
            "stage_artifacts": dict(run.stage_artifacts_json or {}),
            "enabled_mcp_services": list(run.enabled_mcp_services_json or []),
            "enabled_skill_ids": list(run.enabled_skill_ids_json or []),
            "summary": run.summary,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }

    async def _get_run(self, db: AsyncSession, run_id: str, current_user: object) -> WorkflowRun:
        run = await db.get(WorkflowRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        if str(run.user_id) != str(getattr(current_user, "id")):
            raise HTTPException(status_code=403, detail="No access to this workflow run")
        return run

    async def list_runs(self, db: AsyncSession, current_user: object, limit: int = 20) -> list[dict[str, Any]]:
        user_id = str(getattr(current_user, "id"))
        rows = await db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.user_id == user_id)
            .order_by(desc(WorkflowRun.created_at))
            .limit(limit)
        )
        runs = list(rows.scalars().all())
        site_ids = {str(run.site_id) for run in runs}
        site_map: dict[str, Site] = {}
        if site_ids:
            site_rows = await db.execute(select(Site).where(Site.id.in_(site_ids)))
            site_map = {str(site.id): site for site in site_rows.scalars().all()}
        return [self.serialize_run(run, site=site_map.get(str(run.site_id))) for run in runs]

    async def get_current_run(self, db: AsyncSession, current_user: object, site_id: str) -> dict[str, Any] | None:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        rows = await db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.site_id == site.id, WorkflowRun.user_id == getattr(current_user, "id"))
            .order_by(desc(WorkflowRun.created_at))
            .limit(1)
        )
        run = rows.scalars().first()
        return self.serialize_run(run, site=site) if run else None

    async def create_run(self, db: AsyncSession, current_user: object, site_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        name = str(payload.get("name") or "").strip() or f"{site.name} 六阶段开发"
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            site_id=site.id,
            user_id=str(getattr(current_user, "id")),
            name=name,
            status="active",
            current_stage=WORKFLOW_STAGES[0],
            stage_status_json=self._initial_stage_status(),
            stage_artifacts_json={},
            enabled_mcp_services_json=list(payload.get("enabled_mcp_services") or []),
            enabled_skill_ids_json=list(payload.get("enabled_skill_ids") or []),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await self._sync_artifact_index(site, run)
        return self.serialize_run(run, site=site)

    async def generate_stage(
        self,
        db: AsyncSession,
        current_user: object,
        run_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        run = await self._get_run(db, run_id, current_user)
        site = await db.get(Site, run.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Workflow site not found")
        stage = str(payload.get("stage") or run.current_stage).strip() or run.current_stage
        if stage not in WORKFLOW_STAGES:
            raise HTTPException(status_code=400, detail="Invalid workflow stage")
        if stage != run.current_stage:
            raise HTTPException(status_code=409, detail="Only the current stage can be generated")

        title = WORKFLOW_STAGE_LABELS[stage]
        content = str(payload.get("content") or "").strip()
        notes = str(payload.get("notes") or "").strip()
        previous_stage = WORKFLOW_STAGES[max(0, WORKFLOW_STAGES.index(stage) - 1)]
        previous_artifact = ""
        if stage != WORKFLOW_STAGES[0]:
            previous_path = self._stage_file(site.site_id, str(run.id), previous_stage)
            if previous_path.exists():
                previous_artifact = previous_path.read_text(encoding="utf-8").strip()

        if not content:
            content = (
                f"# {title}\n\n"
                f"- 站点: {site.name}\n"
                f"- 站点 ID: {site.site_id}\n"
                f"- 当前阶段: {title}\n\n"
                "## 本阶段目标\n\n"
                f"{notes or '请围绕当前需求补全本阶段结论。'}\n"
            )
            if previous_artifact:
                content += f"\n## 上一阶段参考\n\n{previous_artifact[:4000]}\n"

        path = self._stage_file(site.site_id, str(run.id), stage)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        stage_status = dict(run.stage_status_json or {})
        stage_status[stage] = "draft"
        artifacts = dict(run.stage_artifacts_json or {})
        artifacts[stage] = str(path.relative_to(site_service.site_root(site.site_id)))
        run.stage_status_json = stage_status
        run.stage_artifacts_json = artifacts
        await db.commit()
        await db.refresh(run)
        await self._sync_artifact_index(site, run)
        return {
            "ok": True,
            "run": self.serialize_run(run, site=site),
            "stage": stage,
            "content": content,
            "artifact_path": artifacts[stage],
        }

    async def confirm_stage(self, db: AsyncSession, current_user: object, run_id: str) -> dict[str, Any]:
        run = await self._get_run(db, run_id, current_user)
        site = await db.get(Site, run.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Workflow site not found")
        stage = run.current_stage
        artifact_path = self._stage_file(site.site_id, str(run.id), stage)
        if not artifact_path.exists():
            raise HTTPException(status_code=409, detail="Current stage artifact is missing")
        stage_status = dict(run.stage_status_json or {})
        stage_status[stage] = "confirmed"
        stage_index = WORKFLOW_STAGES.index(stage)
        if stage_index == len(WORKFLOW_STAGES) - 1:
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
        else:
            next_stage = WORKFLOW_STAGES[stage_index + 1]
            run.current_stage = next_stage
            stage_status[next_stage] = "draft"
        run.stage_status_json = stage_status
        await db.commit()
        await db.refresh(run)
        await self._sync_artifact_index(site, run)
        return {"ok": True, "run": self.serialize_run(run, site=site)}

    async def get_run_detail(self, db: AsyncSession, current_user: object, run_id: str) -> dict[str, Any]:
        run = await self._get_run(db, run_id, current_user)
        site = await db.get(Site, run.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Workflow site not found")
        return self.serialize_run(run, site=site)

    async def get_artifacts(self, db: AsyncSession, current_user: object, run_id: str) -> dict[str, Any]:
        run = await self._get_run(db, run_id, current_user)
        site = await db.get(Site, run.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Workflow site not found")
        artifacts: dict[str, Any] = {}
        for stage in WORKFLOW_STAGES:
            path = self._stage_file(site.site_id, str(run.id), stage)
            artifacts[stage] = {
                "label": WORKFLOW_STAGE_LABELS[stage],
                "path": str(path.relative_to(site_service.site_root(site.site_id))) if path.exists() else "",
                "content": path.read_text(encoding="utf-8") if path.exists() else "",
            }
        return {"ok": True, "run": self.serialize_run(run, site=site), "artifacts": artifacts}

    async def _sync_artifact_index(self, site: Site, run: WorkflowRun) -> None:
        data = self.serialize_run(run, site=site)
        paths = self._workflow_paths(site.site_id, str(run.id))
        paths["run_root"].mkdir(parents=True, exist_ok=True)
        meta_path = paths["run_root"] / "meta.json"
        meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["current_file"].write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        history_path = self._history_file(site.site_id, str(run.id))
        history_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


workflow_service = WorkflowService()
