from __future__ import annotations

import html
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Site, SiteSkillBinding, Skill
from backend.services.site_service import site_service


def _extract_title(markdown: str) -> str:
    for line in (markdown or "").splitlines():
        cleaned = line.strip()
        if cleaned.startswith("# "):
            return cleaned[2:].strip()
    return ""


class SkillService:
    def serialize(self, skill: Skill, *, bound_site_ids: list[str] | None = None) -> dict[str, Any]:
        return {
            "id": str(skill.id),
            "name": skill.name,
            "description": skill.description,
            "scope": skill.scope,
            "content": skill.content,
            "triggers": list(skill.triggers_json or []),
            "enabled": bool(skill.enabled),
            "source_type": skill.source_type,
            "source_url": skill.source_url,
            "bound_site_ids": bound_site_ids or [],
            "created_at": skill.created_at.isoformat() if skill.created_at else None,
            "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
        }

    async def _skill_with_bindings(self, db: AsyncSession, current_user: object, skill_id: str) -> tuple[Skill, list[str]]:
        skill = await db.get(Skill, skill_id)
        user_id = str(getattr(current_user, "id"))
        if skill is None or str(skill.user_id) != user_id:
            raise HTTPException(status_code=404, detail="Skill not found")
        rows = await db.execute(select(SiteSkillBinding).where(SiteSkillBinding.skill_id == skill.id))
        bound_site_db_ids = [row.site_id for row in rows.scalars().all()]
        public_ids: list[str] = []
        if bound_site_db_ids:
            sites = await db.execute(select(Site).where(Site.id.in_(bound_site_db_ids)))
            public_ids = [site.site_id for site in sites.scalars().all()]
        return skill, public_ids

    async def list_skills(self, db: AsyncSession, current_user: object) -> list[dict[str, Any]]:
        user_id = str(getattr(current_user, "id"))
        rows = await db.execute(select(Skill).where(Skill.user_id == user_id).order_by(Skill.created_at.desc()))
        skills = rows.scalars().all()
        bindings = await db.execute(select(SiteSkillBinding))
        binding_map: dict[str, list[str]] = {}
        raw_bindings = list(bindings.scalars().all())
        if raw_bindings:
            sites = await db.execute(select(Site))
            site_public = {str(site.id): site.site_id for site in sites.scalars().all()}
            for binding in raw_bindings:
                binding_map.setdefault(str(binding.skill_id), []).append(site_public.get(str(binding.site_id), ""))
        return [self.serialize(skill, bound_site_ids=[item for item in binding_map.get(str(skill.id), []) if item]) for skill in skills]

    async def create_skill(self, db: AsyncSession, current_user: object, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = str(getattr(current_user, "id"))
        content = str(payload.get("content") or "").strip()
        name = str(payload.get("name") or "").strip() or _extract_title(content) or "未命名 Skill"
        skill = Skill(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=name,
            description=str(payload.get("description") or "").strip(),
            scope=str(payload.get("scope") or "global").strip() or "global",
            content=content,
            triggers_json=list(payload.get("triggers") or []),
            enabled=bool(payload.get("enabled", True)),
            source_type=str(payload.get("source_type") or "manual").strip() or "manual",
            source_url=str(payload.get("source_url") or "").strip(),
        )
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
        return self.serialize(skill)

    async def update_skill(self, db: AsyncSession, current_user: object, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        skill, bound_site_ids = await self._skill_with_bindings(db, current_user, skill_id)
        allowed = {"name", "description", "scope", "content", "triggers_json", "enabled", "source_type", "source_url"}
        aliases = {"triggers": "triggers_json"}
        for key, value in payload.items():
            target_key = aliases.get(key, key)
            if target_key in allowed:
                setattr(skill, target_key, value)
        await db.commit()
        await db.refresh(skill)
        return self.serialize(skill, bound_site_ids=bound_site_ids)

    async def delete_skill(self, db: AsyncSession, current_user: object, skill_id: str) -> None:
        skill, _ = await self._skill_with_bindings(db, current_user, skill_id)
        await db.execute(delete(SiteSkillBinding).where(SiteSkillBinding.skill_id == skill.id))
        await db.delete(skill)
        await db.commit()

    async def bind_site(self, db: AsyncSession, current_user: object, skill_id: str, site_id: str, bind: bool = True) -> dict[str, Any]:
        skill, _ = await self._skill_with_bindings(db, current_user, skill_id)
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        rows = await db.execute(
            select(SiteSkillBinding).where(
                SiteSkillBinding.skill_id == skill.id,
                SiteSkillBinding.site_id == site.id,
            )
        )
        binding = rows.scalars().first()
        if bind and binding is None:
            db.add(SiteSkillBinding(site_id=site.id, skill_id=skill.id))
        if not bind and binding is not None:
            await db.delete(binding)
        await db.commit()
        skill, bound_site_ids = await self._skill_with_bindings(db, current_user, skill_id)
        return self.serialize(skill, bound_site_ids=bound_site_ids)

    async def import_skill(self, db: AsyncSession, current_user: object, payload: dict[str, Any]) -> dict[str, Any]:
        import_type = str(payload.get("type") or "").strip()
        if import_type == "markdown":
            markdown = str(payload.get("markdown") or payload.get("content") or "").strip()
            if not markdown:
                raise HTTPException(status_code=400, detail="markdown is required")
            return await self.create_skill(
                db,
                current_user,
                {
                    "name": str(payload.get("name") or "").strip() or _extract_title(markdown),
                    "description": str(payload.get("description") or "").strip(),
                    "content": markdown,
                    "triggers": payload.get("triggers") or [],
                    "enabled": bool(payload.get("enabled", True)),
                    "source_type": "markdown",
                    "source_url": "",
                },
            )
        if import_type == "skills_sh":
            url = str(payload.get("url") or "").strip()
            if not url.startswith("https://skills.sh/"):
                raise HTTPException(status_code=400, detail="skills.sh URL is required")
            parsed = await self._import_from_skills_sh(url)
            return await self.create_skill(
                db,
                current_user,
                {
                    **parsed,
                    "enabled": bool(payload.get("enabled", True)),
                    "source_type": "skills.sh",
                    "source_url": url,
                },
            )
        raise HTTPException(status_code=400, detail="Unsupported import type")

    async def _import_from_skills_sh(self, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, trust_env=False) as client:
                response = await client.get(url)
                response.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to fetch skills.sh page: {exc}") from exc

        text = response.text
        title_match = re.search(r"<title>([^<]+)</title>", text, re.IGNORECASE)
        name = (title_match.group(1) if title_match else "Imported Skill").split(" by ")[0].strip()
        repo_match = re.search(r'<div class="text-sm font-mono uppercase text-white mb-2"><span>Repository</span></div><a[^>]+title="([^"]+)"', text)
        repo_name = repo_match.group(1).strip() if repo_match else ""
        summary_match = re.search(r"<div class=\"text-xs font-mono uppercase text-\\(--ds-gray-600\\) mb-3\">Summary</div><div[^>]*><div[^>]*><p><strong>(.*?)</strong></p>", text, re.DOTALL)
        description = html.unescape(re.sub(r"<[^>]+>", "", summary_match.group(1))).strip() if summary_match else ""

        skill_block = ""
        skill_match = re.search(r"<span>SKILL\.md</span></div><div class=\"prose[^>]*\">(.*?)</div></div></div><div class=\" lg:col-span-3\">", text, re.DOTALL)
        if skill_match:
            skill_block = skill_match.group(1)
        if not skill_block:
            script_match = re.search(r'"__html":"(.*?)"\}\}\]\n', text, re.DOTALL)
            if script_match:
                skill_block = script_match.group(1).encode("utf-8").decode("unicode_escape")

        plain = html.unescape(re.sub(r"</(h1|h2|h3|p|li|ul)>", "\n", skill_block))
        plain = re.sub(r"<[^>]+>", "", plain)
        plain = re.sub(r"\n{3,}", "\n\n", plain).strip()
        if not plain:
            plain = f"# {name}\n\nImported from {url}"

        description = description or plain.splitlines()[0].replace("# ", "").strip()
        triggers = [item for item in {name, repo_name, Path(url).name} if item]
        return {
            "name": name,
            "description": description,
            "content": plain,
            "triggers": triggers,
        }

    async def get_bound_skills(self, db: AsyncSession, current_user: object, site_id: str) -> list[dict[str, Any]]:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        user_id = str(getattr(current_user, "id"))
        rows = await db.execute(
            select(Skill)
            .join(SiteSkillBinding, SiteSkillBinding.skill_id == Skill.id)
            .where(
                Skill.user_id == user_id,
                Skill.enabled.is_(True),
                SiteSkillBinding.site_id == site.id,
            )
            .order_by(Skill.created_at.desc())
        )
        return [self.serialize(skill, bound_site_ids=[site.site_id]) for skill in rows.scalars().all()]

    async def get_selected_skills(
        self,
        db: AsyncSession,
        current_user: object,
        site_id: str,
        skill_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        bound_skills = await self.get_bound_skills(db, current_user, site_id)
        if not skill_ids:
            return bound_skills
        selected = set(skill_ids)
        return [skill for skill in bound_skills if skill["id"] in selected]


skill_service = SkillService()
