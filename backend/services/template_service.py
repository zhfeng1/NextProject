from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Template
from backend.services.site_service import site_service
from backend.utils.minio import download_object


class TemplateService:
    def serialize_template(self, template: Template) -> dict[str, Any]:
        return {
            "id": str(template.id),
            "name": template.name,
            "slug": template.slug,
            "category": getattr(template, "category", None),
            "description": getattr(template, "description", None),
            "thumbnail_url": getattr(template, "thumbnail_url", None),
            "code_archive_url": getattr(template, "code_archive_url", None),
            "tech_stack": getattr(template, "tech_stack", None),
            "usage_count": getattr(template, "usage_count", 0),
            "rating": float(getattr(template, "rating", 0.0) or 0.0),
        }

    async def list_templates(
        self,
        db: AsyncSession,
        *,
        category: str | None = None,
        search: str | None = None,
        limit: int = 20,
    ) -> list[Template]:
        query = select(Template).where(Template.is_public.is_(True))
        if category:
            query = query.where(Template.category == category)
        if search:
            query = query.where(Template.name.ilike(f"%{search}%"))
        query = query.order_by(Template.usage_count.desc(), Template.created_at.desc()).limit(limit)
        rows = await db.execute(query)
        return list(rows.scalars().all())

    async def create_site_from_template(
        self,
        db: AsyncSession,
        *,
        template_id: str,
        site_name: str,
        current_user: object,
    ):
        template = await db.get(Template, template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        site = await site_service.create_site(
            db,
            current_user=current_user,
            site_id=None,
            name=site_name or template.name,
            template_id=str(template.id),
            auto_start=False,
            config={"tech_stack": getattr(template, "tech_stack", {}) or {}},
        )
        if getattr(template, "code_archive_url", None):
            archive_path = download_object(template.code_archive_url)
            notes = site_service.load_site_data(site.site_id)
            notes.setdefault("notes", []).append(f"模板代码来源：{archive_path}")
            site_service.save_site_data(site.site_id, notes)
        template.usage_count = int(getattr(template, "usage_count", 0) or 0) + 1
        await db.commit()
        await db.refresh(site)
        return site


template_service = TemplateService()
