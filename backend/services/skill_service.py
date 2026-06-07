from __future__ import annotations

import html
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Site, SkillConfig
from backend.services.site_service import site_service


SCOPE_PRIORITY = {"global": 1, "project": 2, "repo": 3}


def _extract_title(markdown: str) -> str:
    for line in (markdown or "").splitlines():
        cleaned = line.strip()
        if cleaned.startswith("# "):
            return cleaned[2:].strip()
    return ""


class SkillService:
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

    def serialize(self, skill: SkillConfig, *, site_public_id: str = "") -> dict[str, Any]:
        return {
            "id": str(skill.id),
            "name": skill.name,
            "description": skill.description,
            "scope_type": skill.scope_type,
            "scope": skill.scope_type,
            "project_id": str(skill.project_id) if skill.project_id else "",
            "site_id": site_public_id or (str(skill.site_id) if skill.site_id else ""),
            "content": skill.content,
            "triggers": list(skill.triggers_json or []),
            "enabled": bool(skill.enabled),
            "source_type": skill.source_type,
            "source_url": skill.source_url,
            "created_at": skill.created_at.isoformat() if skill.created_at else None,
            "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
        }

    async def _site_public_map(self, db: AsyncSession, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        rows = await db.execute(select(Site).where(Site.id.in_(ids)))
        return {str(site.id): site.site_id for site in rows.scalars().all()}

    async def list_skills(
        self,
        db: AsyncSession,
        current_user: object,
        *,
        project_id: str | None = None,
        site_id: str | None = None,
        scope_type: str | None = None,
    ) -> list[dict[str, Any]]:
        site_db_id = await self._resolve_site_db_id(db, current_user, site_id)
        query = select(SkillConfig)
        if scope_type:
            query = query.where(SkillConfig.scope_type == scope_type)
        if project_id:
            query = query.where(SkillConfig.project_id == project_id)
        if site_db_id:
            query = query.where(SkillConfig.site_id == site_db_id)
        rows = list((await db.execute(query.order_by(SkillConfig.created_at.desc()))).scalars().all())
        site_map = await self._site_public_map(db, [str(row.site_id) for row in rows if row.site_id])
        return [self.serialize(skill, site_public_id=site_map.get(str(skill.site_id), "")) for skill in rows]

    async def create_skill(self, db: AsyncSession, current_user: object, payload: dict[str, Any]) -> dict[str, Any]:
        content = str(payload.get("content") or payload.get("markdown") or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="content is required")
        scope_type = str(payload.get("scope_type") or payload.get("scope") or "global").strip() or "global"
        project_id = str(payload.get("project_id") or "").strip() or None
        site_public_id = str(payload.get("site_id") or "").strip() or None
        site_db_id = await self._resolve_site_db_id(db, current_user, site_public_id)
        if scope_type != "project":
            project_id = None
        if scope_type != "repo":
            site_db_id = None
            site_public_id = None
        self._validate_scope(scope_type, project_id, site_db_id)
        skill = SkillConfig(
            id=str(uuid.uuid4()),
            name=str(payload.get("name") or "").strip() or _extract_title(content) or "未命名 Skill",
            description=str(payload.get("description") or "").strip(),
            scope_type=scope_type,
            project_id=project_id,
            site_id=site_db_id,
            content=content,
            triggers_json=list(payload.get("triggers") or []),
            enabled=bool(payload.get("enabled", True)),
            source_type=str(payload.get("source_type") or "manual").strip() or "manual",
            source_url=str(payload.get("source_url") or "").strip(),
        )
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
        return self.serialize(skill, site_public_id=site_public_id or "")

    async def update_skill(self, db: AsyncSession, current_user: object, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        skill = await db.get(SkillConfig, skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        if "scope_type" in payload or "scope" in payload or "project_id" in payload or "site_id" in payload:
            scope_type = str(payload.get("scope_type") or payload.get("scope") or skill.scope_type).strip() or "global"
            project_id = str(payload.get("project_id") or "").strip() or None
            site_public_id = str(payload.get("site_id") or "").strip() or None
            site_db_id = await self._resolve_site_db_id(db, current_user, site_public_id)
            if scope_type != "project":
                project_id = None
            if scope_type != "repo":
                site_db_id = None
                site_public_id = None
            self._validate_scope(scope_type, project_id, site_db_id)
            skill.scope_type = scope_type
            skill.project_id = project_id
            skill.site_id = site_db_id
        else:
            site_public_id = ""
        aliases = {"triggers": "triggers_json", "scope": "scope_type"}
        allowed = {"name", "description", "content", "triggers_json", "enabled", "source_type", "source_url"}
        for key, value in payload.items():
            target = aliases.get(key, key)
            if target in allowed:
                setattr(skill, target, value)
        await db.commit()
        await db.refresh(skill)
        return self.serialize(skill, site_public_id=site_public_id)

    async def delete_skill(self, db: AsyncSession, current_user: object, skill_id: str) -> None:
        skill = await db.get(SkillConfig, skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        await db.delete(skill)
        await db.commit()

    async def import_skill(self, db: AsyncSession, current_user: object, payload: dict[str, Any]) -> dict[str, Any]:
        import_type = str(payload.get("type") or "").strip()
        if import_type == "markdown":
            markdown = str(payload.get("markdown") or payload.get("content") or "").strip()
            if not markdown:
                raise HTTPException(status_code=400, detail="markdown is required")
            return await self.create_skill(db, current_user, {**payload, "content": markdown, "source_type": "markdown"})
        if import_type == "skills_sh":
            url = str(payload.get("url") or "").strip()
            if not url.startswith("https://skills.sh/"):
                raise HTTPException(status_code=400, detail="skills.sh URL is required")
            parsed = await self._import_from_skills_sh(url)
            return await self.create_skill(db, current_user, {**payload, **parsed, "source_type": "skills.sh", "source_url": url})
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
        skill_block = ""
        skill_match = re.search(r"<span>SKILL\.md</span></div><div class=\"prose[^>]*\">(.*?)</div></div></div><div class=\" lg:col-span-3\">", text, re.DOTALL)
        if skill_match:
            skill_block = skill_match.group(1)
        plain = html.unescape(re.sub(r"</(h1|h2|h3|p|li|ul)>", "\n", skill_block))
        plain = re.sub(r"<[^>]+>", "", plain)
        plain = re.sub(r"\n{3,}", "\n\n", plain).strip()
        if not plain:
            plain = f"# {name}\n\nImported from {url}"
        triggers = [item for item in {name, repo_name, Path(url).name} if item]
        return {"name": name, "description": plain.splitlines()[0].replace("# ", "").strip(), "content": plain, "triggers": triggers}

    async def resolve_for_repos(
        self,
        db: AsyncSession,
        *,
        project_id: str | None,
        site_ids: list[str],
        selected_skill_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        conditions = [SkillConfig.scope_type == "global"]
        if project_id:
            conditions.append(SkillConfig.project_id == project_id)
        if site_ids:
            conditions.append(SkillConfig.site_id.in_(site_ids))
        rows = list((await db.execute(select(SkillConfig).where(or_(*conditions), SkillConfig.enabled.is_(True)))).scalars().all())
        selected = {item for item in (selected_skill_ids or []) if item}
        effective: dict[str, SkillConfig] = {}
        for row in rows:
            if selected and str(row.id) not in selected:
                continue
            current = effective.get(row.name)
            if current is None or SCOPE_PRIORITY.get(row.scope_type, 0) >= SCOPE_PRIORITY.get(current.scope_type, 0):
                effective[row.name] = row
        return [self.serialize(row) for row in sorted(effective.values(), key=lambda item: item.name.lower())]

    async def get_bound_skills(self, db: AsyncSession, current_user: object, site_id: str) -> list[dict[str, Any]]:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        return await self.resolve_for_repos(db, project_id=str(site.project_id) if site.project_id else None, site_ids=[str(site.id)])

    async def get_selected_skills(self, db: AsyncSession, current_user: object, site_id: str, skill_ids: list[str] | None = None) -> list[dict[str, Any]]:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        return await self.resolve_for_repos(
            db,
            project_id=str(site.project_id) if site.project_id else None,
            site_ids=[str(site.id)],
            selected_skill_ids=skill_ids,
        )


skill_service = SkillService()
