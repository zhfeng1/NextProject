from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.metrics import active_sites_total
from backend.utils.validation import ensure_site_id

from backend.models import Site, SiteStatus, Template

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

DEFAULT_DOCS_README = """# Project Docs

本目录用于沉淀需求、设计说明和模块文档。

- 新需求会默认记录到 `requirements.md`
- AI 完成修改任务后，应按模块整理本目录下的文档
"""

DEFAULT_BACKEND_APP = """import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "backend" / "site_data.json"

app = FastAPI(title="新网站")
app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "frontend")), name="assets")


@app.get("/api/info")
def get_info():
    if not DATA_FILE.exists():
        return {"title": "新网站", "requirement": "", "notes": []}
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


@app.get("/{path:path}")
def serve_frontend(path: str):
    return FileResponse(str(BASE_DIR / "frontend" / "index.html"))
"""

DEFAULT_FRONTEND_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>新网站</title>
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/axios@1.7.9/dist/axios.min.js"></script>
  <style>
    :root { --bg: #f4f7fb; --card: #ffffff; --text: #213547; --brand: #0e7a7a; }
    body { margin: 0; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; background: linear-gradient(135deg, #eef6ff 0%, #f5fffa 100%); color: var(--text); }
    .wrap { max-width: 980px; margin: 32px auto; padding: 0 16px; }
    .card { background: var(--card); border-radius: 16px; padding: 24px; box-shadow: 0 10px 30px rgba(16, 40, 63, .08); }
    h1 { margin: 0 0 12px; font-size: 32px; }
    .desc { color: #567083; margin: 0 0 18px; line-height: 1.7; }
    .tags { display: flex; gap: 10px; flex-wrap: wrap; }
    .tag { background: #e8f5f5; color: #0f6d6d; border-radius: 999px; padding: 6px 12px; font-size: 13px; }
  </style>
</head>
<body>
  <div id="app" class="wrap">
    <div class="card">
      <h1>{{ info.title }}</h1>
      <p class="desc">网站已创建成功。你可以在管理页继续输入优化要求，系统会自动更新并重启网站。</p>
      <div class="tags">
        <span class="tag">默认后端：Python</span>
        <span class="tag">默认前端：Vue</span>
        <span class="tag">支持持续调整</span>
      </div>
    </div>
  </div>
  <script>
    const { createApp } = Vue;
    createApp({
      data() {
        return { info: { title: '新网站', requirement: '', notes: [] } };
      },
      async mounted() {
        const prefix = window.location.pathname.startsWith('/sites/')
          ? window.location.pathname.replace(/\\/+$/, '')
          : '';
        const r = await axios.get(`${prefix}/api/info`);
        this.info = r.data;
      }
    }).mount('#app');
  </script>
</body>
</html>
"""


class SiteService:
    def site_root(self, site_id: str) -> Path:
        return GENERATED_SITES_ROOT / site_id

    def docs_root(self, site_id: str) -> Path:
        return self.site_root(site_id) / "docs"

    def np_root(self, site_id: str) -> Path:
        return self.site_root(site_id) / ".np"

    def _ensure_docs_structure(self, root: Path) -> None:
        docs_dir = root / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        readme_file = docs_dir / "README.md"
        if not readme_file.exists():
            readme_file.write_text(DEFAULT_DOCS_README, encoding="utf-8")

        legacy_requirements = root / "REQUIREMENTS.md"
        requirements_file = docs_dir / "requirements.md"
        if legacy_requirements.exists():
            if not requirements_file.exists() or not requirements_file.read_text(encoding="utf-8").strip():
                requirements_file.write_text(legacy_requirements.read_text(encoding="utf-8"), encoding="utf-8")
            legacy_requirements.unlink()

    def _ensure_np_structure(self, root: Path) -> None:
        workflows_root = root / ".np" / "workflows"
        (workflows_root / "runs").mkdir(parents=True, exist_ok=True)
        (workflows_root / "current").mkdir(parents=True, exist_ok=True)
        (workflows_root / "history").mkdir(parents=True, exist_ok=True)

    def requirements_file(self, site_id: str) -> Path:
        root = self.ensure_site_structure(site_id)
        self._ensure_docs_structure(root)
        return root / "docs" / "requirements.md"

    def _build_authenticated_git_url(self, git_url: str, username: str | None, password: str | None) -> str:
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

        clone_url = self._build_authenticated_git_url(git_url, git_username, git_password)
        clone_command = [git_bin, "clone"]
        if git_branch:
            clone_command.extend(["--branch", git_branch, "--single-branch"])
        clone_command.extend([clone_url, str(root)])
        try:
            subprocess.run(
                clone_command,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            error = (exc.stderr or exc.stdout or "git clone failed").strip()
            raise HTTPException(status_code=400, detail=f"Failed to clone git repository: {error}") from exc

        if not (root / ".git").exists():
            raise HTTPException(status_code=400, detail="Cloned repository is missing .git metadata")

        self._ensure_docs_structure(root)
        self._ensure_np_structure(root)
        return root

    def preview_url_for_site(self, site_id: str) -> str:
        return f"/preview/{site_id}/"

    def resolve_site_path(self, site_id: str, relative_path: str = "") -> Path:
        root = self.ensure_site_structure(site_id).resolve()
        target = (root / (relative_path or "")).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid file path") from exc
        return target

    def list_site_files(self, site_id: str, relative_path: str = "") -> dict[str, Any]:
        target = self.resolve_site_path(site_id, relative_path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Directory not found")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        root = self.site_root(site_id).resolve()
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

    def read_site_file(self, site_id: str, relative_path: str) -> dict[str, Any]:
        if not relative_path:
            raise HTTPException(status_code=400, detail="File path is required")
        target = self.resolve_site_path(site_id, relative_path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        if not target.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")

        raw = target.read_bytes()
        preview = raw[:FILE_PREVIEW_MAX_BYTES]
        is_binary = b"\x00" in preview
        content = "" if is_binary else preview.decode("utf-8", errors="replace")
        root = self.site_root(site_id).resolve()
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
        (root / "backend").mkdir(parents=True, exist_ok=True)
        (root / "frontend").mkdir(parents=True, exist_ok=True)
        self._ensure_docs_structure(root)
        self._ensure_np_structure(root)
        data_file = root / "backend" / "site_data.json"
        if not data_file.exists():
            data_file.write_text(json.dumps(DEFAULT_SITE_DATA, ensure_ascii=False, indent=2), encoding="utf-8")
        app_file = root / "backend" / "app.py"
        if not app_file.exists():
            app_file.write_text(DEFAULT_BACKEND_APP, encoding="utf-8")
        html_file = root / "frontend" / "index.html"
        if not html_file.exists():
            html_file.write_text(DEFAULT_FRONTEND_HTML, encoding="utf-8")
        # Codex 要求在 git 仓库中运行
        git_bin = shutil.which("git")
        if not git_bin:
            raise RuntimeError("git is required in the runtime image to initialize generated site repositories")
        if not (root / ".git").exists():
            subprocess.run([git_bin, "init"], cwd=str(root), capture_output=True, check=True)
            subprocess.run([git_bin, "add", "."], cwd=str(root), capture_output=True, check=True)
            subprocess.run(
                [git_bin, "commit", "-m", "Initial site structure", "--allow-empty"],
                cwd=str(root),
                capture_output=True,
                check=True,
                env={**os.environ, "GIT_AUTHOR_NAME": "NextProject", "GIT_AUTHOR_EMAIL": "bot@nextproject",
                     "GIT_COMMITTER_NAME": "NextProject", "GIT_COMMITTER_EMAIL": "bot@nextproject"},
            )
        return root

    def load_site_data(self, site_id: str) -> dict[str, Any]:
        data_file = self.ensure_site_structure(site_id) / "backend" / "site_data.json"
        try:
            data = json.loads(data_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return dict(DEFAULT_SITE_DATA)

    def save_site_data(self, site_id: str, data: dict[str, Any]) -> None:
        root = self.ensure_site_structure(site_id)
        (root / "backend" / "site_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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
        root = self.site_root(site.site_id)
        if not root.exists():
            root = self.ensure_site_structure(site.site_id)
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
        return {
            "id": str(site.id),
            "site_id": site.site_id,
            "name": site.name,
            "status": public_status,
            "port": site.port,
            "template_id": str(site.template_id) if getattr(site, "template_id", None) else None,
            "preview_url": self.preview_url_for_site(site.site_id),
            "internal_url": f"http://127.0.0.1:{site.port}" if getattr(site, "port", None) else None,
            "config": getattr(site, "config", {}) or {},
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
                "git_source": {
                    "url": git_url,
                    "username": git_username or "",
                    "branch": git_branch or "",
                },
            }
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
        data = self.load_site_data(site.site_id)
        data.setdefault("notes", []).append(f"调整：{instruction}")
        self.save_site_data(site.site_id, data)
        await self.restart_site(db, site.site_id, current_user)
        return site

    async def delete_site(self, db: AsyncSession, site_id: str, current_user: object) -> None:
        site = await self.get_site_by_public_id(db, site_id, current_user)
        self._stop_site_process(site.site_id)
        if hasattr(site, "deleted_at"):
            from datetime import datetime, timezone

            site.deleted_at = datetime.now(timezone.utc)
        else:
            await db.delete(site)
        await db.commit()
        shutil.rmtree(self.site_root(site.site_id), ignore_errors=True)

    async def next_version_number(self, db: AsyncSession, site_id: object) -> int:
        from backend.models import SiteVersion

        result = await db.execute(select(func.max(SiteVersion.version_number)).where(SiteVersion.site_id == site_id))
        return int(result.scalar() or 0) + 1


site_service = SiteService()
