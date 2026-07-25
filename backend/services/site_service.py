from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.metrics import active_sites_total
from backend.services.execution_trace_service import redact_execution_text
from backend.utils.validation import ensure_site_id

from backend.models import Site, SiteStatus, Template
from backend.services.site_scaffold_service import python_vue_site_config, site_scaffold_service

SITE_PORT_START = int(os.getenv("SUB_SITE_PORT_START", "19100"))
SITE_PORT_END = int(os.getenv("SUB_SITE_PORT_END", "19999"))
GENERATED_SITES_ROOT = Path(os.getenv("GENERATED_SITES_ROOT", "generated_sites"))
FILE_PREVIEW_MAX_BYTES = int(os.getenv("SITE_FILE_PREVIEW_MAX_BYTES", "262144"))

_SITE_PROCESSES: dict[str, subprocess.Popen[str]] = {}
_SITE_LOCK = threading.Lock()

DEFAULT_SITE_DATA = {
    "title": "新网站",
    "requirement": "",
    "notes": ["初始生成：v2 backend scaffold"],
}


class SiteService:
    def site_root(self, site_id: str) -> Path:
        return GENERATED_SITES_ROOT / site_id

    def docs_root(self, site_id: str) -> Path:
        return self.site_root(site_id) / "docs"

    def np_root(self, site_id: str) -> Path:
        return self.site_root(site_id) / ".np"

    def _ensure_docs_structure(self, root: Path) -> None:
        site_scaffold_service.ensure_support_dirs(root)

    def _ensure_np_structure(self, root: Path) -> None:
        site_scaffold_service.ensure_support_dirs(root)

    def resolve_site_root(self, site: Site) -> Path:
        if getattr(site, "project_id", None):
            from backend.services.project_service import project_service

            return project_service.repo_root(str(site.project_id), site.name)
        return self.site_root(site.site_id)

    def ensure_support_dirs(self, root: Path) -> Path:
        return site_scaffold_service.ensure_existing_site_support(root)

    def initialize_blank_site(self, root: Path) -> Path:
        return site_scaffold_service.initialize_python_vue_site(root)

    def requirements_file(self, site_id: str) -> Path:
        root = self.ensure_site_structure(site_id)
        self._ensure_docs_structure(root)
        return root / "docs" / "requirements.md"

    @staticmethod
    def sanitize_git_url(git_url: str) -> str:
        parts = urlsplit(str(git_url or "").strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return str(git_url or "").strip()
        netloc = parts.hostname
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    @staticmethod
    def git_url_credentials(git_url: str) -> tuple[str, str]:
        parts = urlsplit(str(git_url or "").strip())
        if parts.scheme not in {"http", "https"}:
            return "", ""
        return unquote(parts.username or ""), unquote(parts.password or "")

    def _build_authenticated_git_url(self, git_url: str, username: str | None, password: str | None) -> str:
        embedded_username, embedded_password = self.git_url_credentials(git_url)
        username = username or embedded_username
        password = password or embedded_password
        git_url = self.sanitize_git_url(git_url)
        if not username and not password:
            return git_url
        if password and not username:
            raise HTTPException(status_code=400, detail="git_username is required when git_password is provided")
        parts = urlsplit(git_url)
        if parts.scheme not in {"http", "https"}:
            return git_url
        auth = quote(username or "", safe="")
        if password:
            auth = f"{auth}:{quote(password, safe='')}"
        netloc = f"{auth}@{parts.hostname or ''}"
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    @contextmanager
    def git_network_env(self, username: str = "", password: str = "") -> Iterator[dict[str, str]]:
        with tempfile.TemporaryDirectory(prefix="nextproject-git-auth-") as temp_dir:
            askpass = Path(temp_dir) / "askpass.sh"
            askpass.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  *Username*) printf '%s\\n' \"$NEXT_PROJECT_GIT_USERNAME\" ;;\n"
                "  *Password*) printf '%s\\n' \"$NEXT_PROJECT_GIT_PASSWORD\" ;;\n"
                "  *) printf '\\n' ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            yield {
                **os.environ,
                "GIT_ASKPASS": str(askpass),
                "GIT_ASKPASS_REQUIRE": "force",
                "GIT_TERMINAL_PROMPT": "0",
                "NEXT_PROJECT_GIT_USERNAME": str(username or ""),
                "NEXT_PROJECT_GIT_PASSWORD": str(password or ""),
            }

    def clone_site_repository(
        self,
        site_id: str,
        git_url: str,
        git_username: str | None = None,
        git_password: str | None = None,
        git_branch: str | None = None,
        override_root: Path | None = None,
    ) -> Path:
        git_bin = shutil.which("git")
        if not git_bin:
            raise RuntimeError("git is required in the runtime image to clone site repositories")

        root = override_root if override_root is not None else self.site_root(site_id)
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        root.parent.mkdir(parents=True, exist_ok=True)

        embedded_username, embedded_password = self.git_url_credentials(git_url)
        username = git_username or embedded_username
        password = git_password or embedded_password
        public_url = self.sanitize_git_url(git_url)
        clone_command = [git_bin, "-c", "credential.helper=", "clone"]
        if git_branch:
            clone_command.extend(["--branch", git_branch, "--single-branch"])
        clone_command.extend([public_url, str(root)])
        try:
            with self.git_network_env(username, password) as network_env:
                subprocess.run(
                    clone_command,
                    capture_output=True,
                    text=True,
                    check=True,
                    env=network_env,
                )
        except subprocess.CalledProcessError as exc:
            error = redact_execution_text((exc.stderr or exc.stdout or "git clone failed").strip())
            raise HTTPException(status_code=400, detail=f"Failed to clone git repository: {error}") from exc

        if not (root / ".git").exists():
            raise HTTPException(status_code=400, detail="Cloned repository is missing .git metadata")

        normalized = subprocess.run(
            [git_bin, "remote", "set-url", "origin", public_url],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if normalized.returncode != 0:
            raise HTTPException(status_code=400, detail="Failed to normalize cloned repository origin URL")

        self.ensure_support_dirs(root)
        return root

    def preview_url_for_site(self, site_id: str) -> str:
        return f"/preview/{site_id}/"

    def resolve_site_path(self, site_id: str, relative_path: str = "", override_root: Path | None = None) -> tuple[Path, Path]:
        root = (override_root if override_root is not None else self.ensure_site_structure(site_id)).resolve()
        if not root.exists():
            root.mkdir(parents=True, exist_ok=True)
        target = (root / (relative_path or "")).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid file path") from exc
        return root, target

    def list_site_files(self, site_id: str, relative_path: str = "", override_root: Path | None = None) -> dict[str, Any]:
        root, target = self.resolve_site_path(site_id, relative_path, override_root=override_root)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Directory not found")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        entries: list[dict[str, Any]] = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name == ".git":
                continue
            rel_path = item.relative_to(root).as_posix()
            entries.append(
                {
                    "name": item.name,
                    "path": rel_path,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                }
            )

        current_path = target.relative_to(root).as_posix() if target != root else ""
        parent_path = target.parent.relative_to(root).as_posix() if target != root else ""
        return {
            "current_path": current_path,
            "parent_path": parent_path,
            "entries": entries,
        }

    def read_site_file(self, site_id: str, relative_path: str, override_root: Path | None = None) -> dict[str, Any]:
        if not relative_path:
            raise HTTPException(status_code=400, detail="File path is required")
        root, target = self.resolve_site_path(site_id, relative_path, override_root=override_root)
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        if not target.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")

        raw = target.read_bytes()
        preview = raw[:FILE_PREVIEW_MAX_BYTES]
        is_binary = b"\x00" in preview
        content = "" if is_binary else preview.decode("utf-8", errors="replace")
        return {
            "path": target.relative_to(root).as_posix(),
            "name": target.name,
            "size": len(raw),
            "truncated": len(raw) > FILE_PREVIEW_MAX_BYTES,
            "binary": is_binary,
            "content": content,
        }

    def is_process_running(self, site_id: str) -> bool:
        with _SITE_LOCK:
            proc = _SITE_PROCESSES.get(site_id)
            if not proc:
                return False
            if proc.poll() is None:
                return True
            _SITE_PROCESSES.pop(site_id, None)
            return False

    def ensure_site_structure(self, site_id: str, override_root: Path | None = None) -> Path:
        root = override_root if override_root is not None else self.site_root(site_id)
        if root.exists() and (root / "backend" / "app.py").exists():
            return self.ensure_support_dirs(root)
        return self.initialize_blank_site(root)

    def load_site_data(self, site_id: str, override_root: Path | None = None) -> dict[str, Any]:
        root = self.ensure_support_dirs(override_root) if override_root is not None else self.ensure_site_structure(site_id)
        data_file = root / "backend" / "site_data.json"
        try:
            data = json.loads(data_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return dict(DEFAULT_SITE_DATA)

    def save_site_data(self, site_id: str, data: dict[str, Any], override_root: Path | None = None) -> None:
        root = self.ensure_support_dirs(override_root) if override_root is not None else self.ensure_site_structure(site_id)
        data_dir = root / "backend"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "site_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _next_port(self, sites: list[Site]) -> int:
        used = {int(site.port) for site in sites if getattr(site, "port", None)}
        for port in range(SITE_PORT_START, SITE_PORT_END + 1):
            if port not in used:
                return port
        raise HTTPException(status_code=500, detail="No free site port available")

    def _build_site_start_command(self, site: Site, port: int, root: Path) -> tuple[list[str], dict[str, str]]:
        config = getattr(site, "config", {}) or {}
        start_command = str(config.get("start_command") or "").strip()
        env = {
            **os.environ,
            "PORT": str(port),
            "HOST": "0.0.0.0",
            "SITE_PORT": str(port),
            "NEXTPROJECT_SITE_PORT": str(port),
            "SITE_ROOT": str(root),
        }
        if start_command:
            return ["sh", "-lc", start_command], env
        return [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", str(port)], env

    def _run_site_process(self, site: Site) -> None:
        root = self.resolve_site_root(site)
        if not root.exists():
            root = self.initialize_blank_site(root) if getattr(site, "project_id", None) else self.ensure_site_structure(site.site_id)
        command, env = self._build_site_start_command(site, int(site.port), root)
        proc = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,
        )
        with _SITE_LOCK:
            existing = _SITE_PROCESSES.get(site.site_id)
            if existing and existing.poll() is None:
                try:
                    os.killpg(existing.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            _SITE_PROCESSES[site.site_id] = proc

    def _stop_site_process(self, site_id: str) -> None:
        with _SITE_LOCK:
            proc = _SITE_PROCESSES.get(site_id)
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        with _SITE_LOCK:
            _SITE_PROCESSES.pop(site_id, None)

    def serialize_site(self, site: Site) -> dict[str, Any]:
        public_status = getattr(site.status, "value", site.status)
        if self.is_process_running(site.site_id):
            public_status = SiteStatus.RUNNING.value
        config = dict(getattr(site, "config", {}) or {})
        git_source = config.get("git_source")
        if isinstance(git_source, dict):
            config["git_source"] = {
                **git_source,
                "url": redact_execution_text(self.sanitize_git_url(str(git_source.get("url") or ""))),
            }
        return {
            "id": str(site.id),
            "site_id": site.site_id,
            "name": site.name,
            "status": public_status,
            "port": site.port,
            "template_id": str(site.template_id) if getattr(site, "template_id", None) else None,
            "preview_url": self.preview_url_for_site(site.site_id),
            "internal_url": f"http://127.0.0.1:{site.port}" if getattr(site, "port", None) else None,
            "project_id": str(site.project_id) if getattr(site, "project_id", None) else None,
            "main_branch": getattr(site, "main_branch", "") or "",
            "config": config,
            "created_at": getattr(site, "created_at", None).isoformat() if getattr(site, "created_at", None) else None,
        }

    async def list_sites(self, db: AsyncSession, user: object, include_deleted: bool = False) -> list[Site]:
        query = select(Site)
        user_id = getattr(user, "id", None)
        org_id = getattr(user, "default_org_id", None)
        if user_id is not None and hasattr(Site, "owner_id"):
            query = query.where(or_(Site.owner_id == user_id, Site.org_id == org_id))
        if not include_deleted and hasattr(Site, "deleted_at"):
            query = query.where(Site.deleted_at.is_(None))
        query = query.order_by(Site.created_at.asc())
        rows = await db.execute(query)
        return list(rows.scalars().all())

    async def get_site_by_public_id(self, db: AsyncSession, site_id: str, current_user: object) -> Site:
        sid = ensure_site_id(site_id)
        query = select(Site).where(Site.site_id == sid)
        row = await db.execute(query)
        site = row.scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"Site not found: {sid}")
        owner_id = getattr(site, "owner_id", None)
        org_id = getattr(site, "org_id", None)
        user_id = getattr(current_user, "id", None)
        user_org_id = getattr(current_user, "default_org_id", None)
        is_superuser = bool(getattr(current_user, "is_superuser", False))
        if not is_superuser and owner_id not in {None, user_id} and org_id not in {None, user_org_id}:
            raise HTTPException(status_code=403, detail="No access to the site")
        return site

    async def create_site(
        self,
        db: AsyncSession,
        current_user: object,
        site_id: str | None,
        name: str | None,
        template_id: str | None = None,
        auto_start: bool = False,
        config: dict[str, Any] | None = None,
        git_url: str | None = None,
        git_username: str | None = None,
        git_password: str | None = None,
        git_branch: str | None = None,
        start_command: str | None = None,
    ) -> Site:
        rows = await db.execute(select(Site))
        all_sites = list(rows.scalars().all())
        existing_ids = {item.site_id for item in all_sites}
        if site_id:
            sid = ensure_site_id(site_id)
            if sid in existing_ids:
                raise HTTPException(status_code=409, detail=f"Site already exists: {sid}")
        else:
            sid = str(uuid.uuid4())
            while sid in existing_ids:
                sid = str(uuid.uuid4())
        site = Site(
            id=str(uuid.uuid4()),
            site_id=sid,
            name=(name or sid).strip() or sid,
            owner_id=getattr(current_user, "id", None),
            org_id=getattr(current_user, "default_org_id", None),
            status=SiteStatus.STOPPED.value,
            port=self._next_port(all_sites),
            template_id=template_id or None,
            config=config or {},
        )
        if template_id:
            template = await db.get(Template, template_id)
            if template and getattr(template, "tech_stack", None):
                site.config = {**(site.config or {}), "tech_stack": template.tech_stack}
        if git_url:
            site.config = {
                **(site.config or {}),
                "source_type": "git",
                "git_source": {
                    "url": git_url,
                    "username": git_username or "",
                    "branch": git_branch or "",
                },
            }
        else:
            site.config = python_vue_site_config(site.config or {})
        if start_command:
            site.config = {
                **(site.config or {}),
                "start_command": start_command,
            }
        db.add(site)
        await db.flush()
        try:
            if git_url:
                self.clone_site_repository(
                    site.site_id,
                    git_url,
                    git_username=git_username,
                    git_password=git_password,
                    git_branch=git_branch,
                )
            else:
                self.ensure_site_structure(site.site_id)
        except Exception:
            await db.rollback()
            raise
        await db.commit()
        await db.refresh(site)
        if auto_start:
            return await self.start_site(db, site.site_id, current_user)
        return site

    async def start_site(self, db: AsyncSession, site_id: str, current_user: object) -> Site:
        site = await self.get_site_by_public_id(db, site_id, current_user)
        self._run_site_process(site)
        site.status = SiteStatus.RUNNING.value
        await db.commit()
        await db.refresh(site)
        active_sites_total.inc()
        return site

    async def stop_site(self, db: AsyncSession, site_id: str, current_user: object) -> Site:
        site = await self.get_site_by_public_id(db, site_id, current_user)
        self._stop_site_process(site.site_id)
        site.status = SiteStatus.STOPPED.value
        await db.commit()
        await db.refresh(site)
        active_sites_total.dec()
        return site

    async def restart_site(self, db: AsyncSession, site_id: str, current_user: object) -> Site:
        await self.stop_site(db, site_id, current_user)
        return await self.start_site(db, site_id, current_user)

    async def apply_adjustment(self, db: AsyncSession, site_id: str, current_user: object, instruction: str) -> Site:
        if not instruction:
            raise HTTPException(status_code=400, detail="instruction is required")
        site = await self.get_site_by_public_id(db, site_id, current_user)
        root = self.resolve_site_root(site)
        data = self.load_site_data(site.site_id, override_root=root)
        data.setdefault("notes", []).append(f"调整：{instruction}")
        self.save_site_data(site.site_id, data, override_root=root)
        await self.restart_site(db, site.site_id, current_user)
        return site

    async def delete_site(self, db: AsyncSession, site_id: str, current_user: object) -> None:
        site = await self.get_site_by_public_id(db, site_id, current_user)
        root = self.resolve_site_root(site)
        self._stop_site_process(site.site_id)
        if hasattr(site, "deleted_at"):
            from datetime import datetime, timezone

            site.deleted_at = datetime.now(timezone.utc)
        else:
            await db.delete(site)
        await db.commit()
        shutil.rmtree(root, ignore_errors=True)

    async def next_version_number(self, db: AsyncSession, site_id: object) -> int:
        from backend.models import SiteVersion

        result = await db.execute(select(func.max(SiteVersion.version_number)).where(SiteVersion.site_id == site_id))
        return int(result.scalar() or 0) + 1


site_service = SiteService()
