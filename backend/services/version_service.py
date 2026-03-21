from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SiteVersion
from backend.services.site_service import site_service
from backend.utils.minio import download_object, upload_file


class VersionService:
    def serialize_version(self, version: SiteVersion) -> dict[str, Any]:
        return {
            "id": str(version.id),
            "site_id": str(version.site_id),
            "version_number": version.version_number,
            "snapshot_url": getattr(version, "snapshot_url", None),
            "commit_message": getattr(version, "commit_message", None),
            "diff_summary": getattr(version, "diff_summary", None) or {},
            "is_deployed": bool(getattr(version, "is_deployed", False)),
            "created_at": getattr(version, "created_at", None).isoformat() if getattr(version, "created_at", None) else None,
        }

    async def list_versions(self, db: AsyncSession, site_id: str, current_user: object) -> list[SiteVersion]:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        rows = await db.execute(
            select(SiteVersion).where(SiteVersion.site_id == site.id).order_by(SiteVersion.version_number.desc())
        )
        return list(rows.scalars().all())

    async def create_snapshot(
        self,
        *,
        db: AsyncSession,
        site_id: str,
        commit_message: str,
        created_by: str,
        current_user: object,
    ) -> SiteVersion:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        version_number = await site_service.next_version_number(db, site.id)
        root = site_service.site_root(site.site_id)
        site_service.ensure_site_structure(site.site_id)
        fd, archive_path = tempfile.mkstemp(prefix=f"{site.site_id}-v{version_number}-", suffix=".tar.gz")
        os.close(fd)
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(root, arcname=".")
        snapshot_url = upload_file(archive_path, "site-versions", f"{site.site_id}/v{version_number}.tar.gz")
        version = SiteVersion(
            id=str(uuid.uuid4()),
            site_id=site.id,
            version_number=version_number,
            snapshot_url=snapshot_url,
            commit_message=commit_message,
            diff_summary={"files_changed": len(list(root.rglob("*")))},
            created_by=created_by,
        )
        db.add(version)
        await db.commit()
        await db.refresh(version)
        Path(archive_path).unlink(missing_ok=True)
        return version

    async def rollback_to_version(
        self,
        db: AsyncSession,
        site_id: str,
        version_number: int,
        current_user: object,
    ) -> SiteVersion:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        rows = await db.execute(
            select(SiteVersion).where(
                SiteVersion.site_id == site.id,
                SiteVersion.version_number == version_number,
            )
        )
        version = rows.scalar_one_or_none()
        if version is None:
            raise HTTPException(status_code=404, detail=f"Version {version_number} not found")
        archive_path = download_object(version.snapshot_url)
        root = site_service.site_root(site.site_id)
        site_service._stop_site_process(site.site_id)
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tar", "-xzf", archive_path, "-C", str(root)], check=True)
        await site_service.start_site(db, site.site_id, current_user)
        return version


version_service = VersionService()
