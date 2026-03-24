from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.models import Template


DEFAULT_TEMPLATES = [
    {
        "name": "SaaS Landing",
        "slug": "saas-landing",
        "category": "landing",
        "description": "A conversion-focused landing page for software products.",
        "thumbnail_url": "https://placehold.co/600x400?text=SaaS+Landing",
        "code_archive_url": "s3://site-templates/saas-landing.tar.gz",
        "tech_stack": {"backend": "fastapi", "frontend": "vue3"},
    },
    {
        "name": "Content Blog",
        "slug": "content-blog",
        "category": "blog",
        "description": "Editorial blog starter with article, category and author pages.",
        "thumbnail_url": "https://placehold.co/600x400?text=Content+Blog",
        "code_archive_url": "s3://site-templates/content-blog.tar.gz",
        "tech_stack": {"backend": "fastapi", "frontend": "vue3"},
    },
    {
        "name": "Analytics Dashboard",
        "slug": "analytics-dashboard",
        "category": "dashboard",
        "description": "Operations dashboard with cards, charts and role-based navigation.",
        "thumbnail_url": "https://placehold.co/600x400?text=Analytics+Dashboard",
        "code_archive_url": "s3://site-templates/analytics-dashboard.tar.gz",
        "tech_stack": {"backend": "fastapi", "frontend": "vue3"},
    },
    {
        "name": "Shop Catalog",
        "slug": "shop-catalog",
        "category": "ecommerce",
        "description": "Catalog storefront with product listing, filters and detail pages.",
        "thumbnail_url": "https://placehold.co/600x400?text=Shop+Catalog",
        "code_archive_url": "s3://site-templates/shop-catalog.tar.gz",
        "tech_stack": {"backend": "fastapi", "frontend": "vue3"},
    },
    {
        "name": "Portfolio Studio",
        "slug": "portfolio-studio",
        "category": "portfolio",
        "description": "Visual portfolio template for agencies and creators.",
        "thumbnail_url": "https://placehold.co/600x400?text=Portfolio+Studio",
        "code_archive_url": "s3://site-templates/portfolio-studio.tar.gz",
        "tech_stack": {"backend": "fastapi", "frontend": "vue3"},
    },
]


async def seed_templates() -> list[str]:
    created: list[str] = []
    async with AsyncSessionLocal() as session:
        for item in DEFAULT_TEMPLATES:
            existing = await session.execute(select(Template).where(Template.slug == item["slug"]))
            if existing.scalar_one_or_none():
                continue
            session.add(Template(**item))
            created.append(item["slug"])
        await session.commit()
    return created


async def async_main() -> None:
    created = await seed_templates()
    print(json.dumps({"ok": True, "created": created}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(async_main())
