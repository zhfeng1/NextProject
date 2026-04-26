from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.requirement import SiteRequirementEvent, SiteRequirementSnapshot
from backend.services.site_service import site_service


class RequirementService:
    async def log_event(
        self,
        db: AsyncSession,
        site_id: str,
        event_type: str,
        content: str,
        conversation_id: str | None = None,
        task_id: str | None = None,
    ) -> SiteRequirementEvent:
        event = SiteRequirementEvent(
            site_id=site_id,
            event_type=event_type,
            content=content,
            conversation_id=conversation_id,
            task_id=task_id,
            processed=False,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event

    async def get_latest_snapshot(
        self, db: AsyncSession, site_id: str
    ) -> SiteRequirementSnapshot | None:
        query = (
            select(SiteRequirementSnapshot)
            .where(SiteRequirementSnapshot.site_id == site_id)
            .order_by(desc(SiteRequirementSnapshot.version))
            .limit(1)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_unprocessed_events(
        self, db: AsyncSession, site_id: str, limit: int = 50
    ) -> list[SiteRequirementEvent]:
        query = (
            select(SiteRequirementEvent)
            .where(
                SiteRequirementEvent.site_id == site_id,
                SiteRequirementEvent.processed == False,
            )
            .order_by(SiteRequirementEvent.created_at.asc())
            .limit(limit)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def create_snapshot(
        self,
        db: AsyncSession,
        site_id: str,
        content: str,
        event_ids: list[str],
        diff_from_previous: str = "",
    ) -> SiteRequirementSnapshot:
        latest = await self.get_latest_snapshot(db, site_id)
        next_version = (latest.version + 1) if latest else 1

        snapshot = SiteRequirementSnapshot(
            site_id=site_id,
            version=next_version,
            content=content,
            diff_from_previous=diff_from_previous,
            event_ids_json=json.dumps(event_ids),
        )
        db.add(snapshot)
        
        # Mark events as processed
        if event_ids:
            await db.execute(
                update(SiteRequirementEvent)
                .where(SiteRequirementEvent.id.in_(event_ids))
                .values(processed=True)
            )
            
        # Optional: Save to file system docs/REQUIREMENTS.md
        try:
            site_root = site_service.site_root(site_id)
            docs_dir = site_root / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            req_file = docs_dir / "REQUIREMENTS.md"
            req_file.write_text(content, encoding="utf-8")
        except Exception:
            pass # ignore fs errors
            
        await db.commit()
        await db.refresh(snapshot)
        return snapshot

    def serialize_event(self, event: SiteRequirementEvent) -> dict[str, Any]:
        return {
            "id": str(event.id),
            "site_id": str(event.site_id),
            "event_type": event.event_type,
            "content": event.content,
            "conversation_id": str(event.conversation_id) if event.conversation_id else None,
            "task_id": event.task_id,
            "processed": event.processed,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }

    def serialize_snapshot(self, snapshot: SiteRequirementSnapshot) -> dict[str, Any]:
        return {
            "id": str(snapshot.id),
            "site_id": str(snapshot.site_id),
            "version": snapshot.version,
            "content": snapshot.content,
            "diff_from_previous": snapshot.diff_from_previous,
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        }

requirement_service = RequirementService()
