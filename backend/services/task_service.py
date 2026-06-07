from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import stat
import subprocess
import uuid
from time import monotonic
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import case, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Project, Site, Task, TaskLog, TaskRepository, TaskStatus
from backend.core.encryption import decrypt_api_key
from backend.services.mcp_service import mcp_service
from backend.services.project_service import project_service
from backend.services.site_service import site_service
from backend.services.skill_service import skill_service
from backend.services.websocket_service import websocket_manager

SUPPORTED_PROVIDERS = {"codex", "claude_code", "gemini_cli"}
SUPPORTED_TASK_TYPES = {"develop_code", "test_local_playwright", "deploy_local", "deploy_apollo", "clone_repo"}
BOARD_STATUSES = {"todo", "queued", "running", "review", "done", "failed", "canceled"}
EXEC_TO_BOARD_STATUS = {
    TaskStatus.QUEUED.value: "queued",
    TaskStatus.RUNNING.value: "running",
    TaskStatus.SUCCESS.value: "done",
    TaskStatus.FAILED.value: "failed",
    TaskStatus.CANCELED.value: "canceled",
}
WORKFLOW_STAGE_LABELS = {
    "research": "研究",
    "ideate": "构思",
    "plan": "计划",
    "execute": "执行",
    "optimize": "优化",
    "review": "评审",
}


class TaskService:
    @staticmethod
    def _normalize_context_url(current_url: str, site: Site | None) -> str:
        raw = (current_url or "").strip()
        if not raw:
            return ""
        if site is None or not getattr(site, "port", None):
            return raw

        internal_base = f"http://127.0.0.1:{site.port}"
        site_slug = str(getattr(site, "site_id", "") or "").strip()
        preview_prefix = f"/preview/{site_slug}"
        try:
            parts = urlsplit(raw)
        except Exception:
            return raw

        path = parts.path or ""
        if not path.startswith(preview_prefix):
            return raw

        forwarded_path = path[len(preview_prefix):] or "/"
        if not forwarded_path.startswith("/"):
            forwarded_path = f"/{forwarded_path}"

        filtered_query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "_ts"]
        return urlunsplit((
            "http",
            f"127.0.0.1:{site.port}",
            forwarded_path,
            urlencode(filtered_query, doseq=True),
            parts.fragment,
        ))

    @staticmethod
    def _format_log_line(source: str, line: str) -> str:
        text = (line or "").rstrip()
        if not text:
            return text
        if text.lstrip().startswith("["):
            return text
        return f"[{source}] {text}"

    @staticmethod
    def _owner_ref(site: Site) -> object:
        return type(
            "UserRef",
            (),
            {"id": site.owner_id, "default_org_id": site.org_id, "is_superuser": True},
        )()

    @staticmethod
    def _write_runtime_file(root: Path, filename: str, data: dict[str, Any] | list[Any]) -> str:
        root.mkdir(parents=True, exist_ok=True)
        path = root / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    @staticmethod
    def _write_api_key_file(runtime_root: Path, api_key_plaintext: str) -> str:
        """Write decrypted API key to a temp file with restricted permissions."""
        runtime_root.mkdir(parents=True, exist_ok=True)
        key_path = runtime_root / "api_key"
        key_path.write_text(api_key_plaintext, encoding="utf-8")
        key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        return str(key_path)

    @staticmethod
    def _cleanup_task_runtime(task_id: str) -> None:
        """Remove the runtime directory for a completed task."""
        runtime_dir = Path("/tmp/nextproject-task-runtime") / str(task_id)
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir, ignore_errors=True)
        codex_home = Path(f"/tmp/nextproject-codex/{task_id}")
        if codex_home.exists():
            shutil.rmtree(codex_home, ignore_errors=True)

    @staticmethod
    def _safe_command_preview(provider: str, model_name: str = "", command_text: str = "") -> str:
        if command_text:
            preview = command_text.strip()
            if len(preview) > 180:
                preview = f"{preview[:177]}..."
            return f"执行命令: $ {preview}"
        if provider == "codex":
            model_part = f" --model {model_name}" if model_name else ""
            return f"执行命令: $ codex exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox{model_part} [prompt hidden]"
        return f"{provider} 任务已启动"

    @staticmethod
    def _task_artifacts_root() -> Path:
        configured = os.getenv("TASK_ARTIFACTS_ROOT", "").strip()
        if configured:
            return Path(configured)
        shared_root = Path("/shared/task_artifacts")
        if shared_root.parent.exists():
            return shared_root
        return Path("data/task_artifacts")

    @staticmethod
    def _provider_output_path(task: Task, provider: str = "") -> Path:
        provider_name = (provider or getattr(task, "provider", "") or "provider").strip() or "provider"
        artifacts_root = TaskService._task_artifacts_root()
        return artifacts_root / str(task.id) / f"{provider_name}-output.log"

    @staticmethod
    def _repo_root_for_site(site: Site) -> Path:
        if getattr(site, "project_id", None):
            return project_service.repo_root(str(site.project_id), site.name)
        return site_service.site_root(site.site_id)

    @staticmethod
    def _project_root_for_task(task: Task, primary_site: Site | None = None) -> Path:
        if getattr(task, "project_id", None):
            return project_service.project_root(str(task.project_id))
        if primary_site is not None:
            return TaskService._repo_root_for_site(primary_site)
        return Path.cwd()

    @staticmethod
    def _git_env() -> dict[str, str]:
        return {
            **os.environ,
            "GIT_AUTHOR_NAME": "NextProject",
            "GIT_AUTHOR_EMAIL": "bot@nextproject",
            "GIT_COMMITTER_NAME": "NextProject",
            "GIT_COMMITTER_EMAIL": "bot@nextproject",
        }

    def _write_mcp_runtime_configs(self, runtime_root: Path, services: list[dict[str, Any]]) -> dict[str, str]:
        codex_home = runtime_root / "codex-home"
        codex_home.mkdir(parents=True, exist_ok=True)
        codex_lines = ['cli_auth_credentials_store = "file"', ""]
        claude_servers: dict[str, Any] = {}
        for service in services:
            service_id = service["service_id"]
            config = dict(service.get("config") or {})
            if config.get("url"):
                codex_lines.append(f'[mcp_servers.{service_id}]')
                codex_lines.append(f'url = {json.dumps(config["url"])}')
                if config.get("bearer_token_env_var"):
                    codex_lines.append(f'bearer_token_env_var = {json.dumps(config["bearer_token_env_var"])}')
                codex_lines.append("enabled = true")
                codex_lines.append("")
                claude_servers[service_id] = {
                    "type": "http",
                    "url": config["url"],
                    **({"headers": config.get("headers")} if config.get("headers") else {}),
                }
            elif config.get("command"):
                args = list(config.get("args") or [])
                env = dict(config.get("env") or {})
                codex_lines.append(f'[mcp_servers.{service_id}]')
                codex_lines.append(f'command = {json.dumps(config["command"])}')
                codex_lines.append(f'args = {json.dumps(args, ensure_ascii=False)}')
                if env:
                    codex_lines.append("[mcp_servers.%s.env]" % service_id)
                    for key, value in env.items():
                        codex_lines.append(f'{key} = {json.dumps(str(value))}')
                codex_lines.append("enabled = true")
                codex_lines.append("")
                claude_servers[service_id] = {
                    "type": "stdio",
                    "command": config["command"],
                    "args": args,
                    "env": env,
                }
        codex_config = codex_home / "config.toml"
        codex_config.write_text("\n".join(codex_lines), encoding="utf-8")
        claude_config = runtime_root / "claude-mcp.json"
        claude_config.write_text(json.dumps({"mcpServers": claude_servers}, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"codex_home": str(codex_home), "claude_mcp_config": str(claude_config)}

    def serialize_task(self, task: Task) -> dict[str, Any]:
        payload = getattr(task, "payload", None) or getattr(task, "payload_json", None) or {}
        result = getattr(task, "result", None) or getattr(task, "result_json", None) or {}
        return {
            "id": str(task.id),
            "site_id": str(getattr(task, "site_id", "") or ""),
            "project_id": str(getattr(task, "project_id", "") or ""),
            "title": getattr(task, "title", "") or payload.get("title") or payload.get("prompt") or getattr(task, "task_type", ""),
            "description": getattr(task, "description", ""),
            "priority": getattr(task, "priority", "") or "medium",
            "assignee": getattr(task, "assignee", ""),
            "board_status": getattr(task, "board_status", "") or EXEC_TO_BOARD_STATUS.get(getattr(task, "status", ""), "queued"),
            "provider": getattr(task, "provider", ""),
            "task_type": getattr(task, "task_type", ""),
            "status": getattr(getattr(task, "status", ""), "value", getattr(task, "status", "")),
            "workflow_stages": list(getattr(task, "workflow_stages_json", None) or []),
            "runtime_config_dir": getattr(task, "runtime_config_dir", ""),
            "payload": payload,
            "result": result,
            "error": getattr(task, "error", ""),
            "created_at": getattr(task, "created_at", None).isoformat() if getattr(task, "created_at", None) else None,
            "started_at": getattr(task, "started_at", None).isoformat() if getattr(task, "started_at", None) else None,
            "finished_at": getattr(task, "finished_at", None).isoformat() if getattr(task, "finished_at", None) else None,
        }

    async def serialize_task_detail(self, db: AsyncSession, task: Task) -> dict[str, Any]:
        data = self.serialize_task(task)
        repos = await self.get_task_repositories(db, str(task.id))
        data["repositories"] = repos
        project = await db.get(Project, task.project_id) if getattr(task, "project_id", None) else None
        data["project_name"] = project.name if project else ""
        return data

    async def get_task(self, db: AsyncSession, task_id: str, current_user: object) -> Task:
        task = await db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        if task.project_id:
            await project_service.get_project(db, str(task.project_id), current_user)
        elif task.site_id:
            site = await db.get(Site, task.site_id)
            if site is None:
                raise HTTPException(status_code=404, detail="Task site not found")
            await site_service.get_site_by_public_id(db, site.site_id, current_user)
        else:
            raise HTTPException(status_code=404, detail="Task target not found")
        return task

    async def get_task_repositories(self, db: AsyncSession, task_id: str) -> list[dict[str, Any]]:
        rows = await db.execute(select(TaskRepository).where(TaskRepository.task_id == task_id))
        bindings = list(rows.scalars().all())
        if not bindings:
            return []
        site_rows = await db.execute(select(Site).where(Site.id.in_([item.site_id for item in bindings])))
        site_map = {str(site.id): site for site in site_rows.scalars().all()}
        result: list[dict[str, Any]] = []
        for item in bindings:
            site = site_map.get(str(item.site_id))
            result.append({
                "site_id": site.site_id if site else str(item.site_id),
                "site_db_id": str(item.site_id),
                "name": site.name if site else "",
                "repo_path": item.repo_path,
                "before_sha": item.before_sha,
                "after_sha": item.after_sha,
                "changed": bool(item.changed),
                "commit_message": item.commit_message,
                "rollback_status": item.rollback_status,
            })
        return result

    async def get_task_provider_output(
        self,
        db: AsyncSession,
        task_id: str,
        current_user: object,
        max_bytes: int = 512_000,
    ) -> dict[str, Any]:
        task = await self.get_task(db, task_id, current_user)
        output_path = self._provider_output_path(task)
        if not output_path.exists():
            result = getattr(task, "result_json", None) or getattr(task, "result", None) or {}
            return {
                "task_id": str(task.id),
                "provider": task.provider,
                "available": bool(result.get("output_tail")),
                "content": str(result.get("output_tail") or ""),
                "truncated": False,
            }
        raw = output_path.read_bytes()
        truncated = len(raw) > max_bytes
        if truncated:
            raw = raw[-max_bytes:]
        content = raw.decode("utf-8", errors="ignore")
        return {
            "task_id": str(task.id),
            "provider": task.provider,
            "available": True,
            "content": content,
            "truncated": truncated,
        }

    async def list_site_tasks(
        self,
        db: AsyncSession,
        site_id: str,
        current_user: object,
        limit: int = 30,
        task_type: str | None = None,
    ) -> list[Task]:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        query = select(Task).where(Task.site_id == site.id)
        if task_type:
            query = query.where(Task.task_type == task_type)
        query = query.order_by(desc(Task.created_at), desc(Task.id)).limit(limit)
        rows = await db.execute(query)
        return list(rows.scalars().all())

    async def list_board_tasks(
        self,
        db: AsyncSession,
        current_user: object,
        *,
        project_id: str | None = None,
        repo_id: str | None = None,
        provider: str | None = None,
        board_status: str | None = None,
        priority: str | None = None,
        keyword: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        visible_sites = await site_service.list_sites(db, current_user, include_deleted=False)
        site_db_ids = [str(site.id) for site in visible_sites]
        project_ids = {str(site.project_id) for site in visible_sites if site.project_id}
        projects = await project_service.list_projects(db, user=current_user)
        project_ids.update(str(project.id) for project in projects)

        query = select(Task)
        visibility = []
        if site_db_ids:
            visibility.append(Task.site_id.in_(site_db_ids))
        if project_ids:
            visibility.append(Task.project_id.in_(project_ids))
        if visibility:
            query = query.where(or_(*visibility))
        else:
            query = query.where(Task.id == "__none__")
        if project_id:
            query = query.where(Task.project_id == project_id)
        if provider:
            query = query.where(Task.provider == provider)
        if board_status:
            query = query.where(Task.board_status == board_status)
        if priority:
            query = query.where(Task.priority == priority)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(or_(Task.title.ilike(like), Task.description.ilike(like), Task.task_type.ilike(like)))
        if repo_id:
            site = await site_service.get_site_by_public_id(db, repo_id, current_user)
            query = query.join(TaskRepository, TaskRepository.task_id == Task.id).where(TaskRepository.site_id == site.id)
        rows = await db.execute(query.order_by(desc(Task.updated_at), desc(Task.created_at)).limit(limit))
        tasks = list(rows.scalars().unique().all())
        return [await self.serialize_task_detail(db, task) for task in tasks]

    async def append_log(
        self,
        db: AsyncSession,
        task: Task,
        line: str,
        level: str = "INFO",
        source: str = "backend",
    ) -> None:
        entry = TaskLog(task_id=task.id, level=level, line=self._format_log_line(source, line))
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        websocket_manager.publish(str(task.id), {
            "type": "log",
            "data": {
                "id": entry.id,
                "level": level,
                "line": entry.line,
                "ts": entry.ts.isoformat() if getattr(entry, "ts", None) else None,
            },
        })

    async def update_status(
        self,
        db: AsyncSession,
        task: Task,
        status: str | TaskStatus,
        *,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> Task:
        task.status = status
        status_value = getattr(status, "value", status)
        task.status = status_value
        now = datetime.now(timezone.utc)
        if status_value == TaskStatus.RUNNING.value:
            task.started_at = now
        if status_value in {TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELED.value}:
            task.finished_at = now
        task.board_status = EXEC_TO_BOARD_STATUS.get(status_value, getattr(task, "board_status", "") or "queued")
        if result is not None:
            setattr(task, "result", result)
            if hasattr(task, "result_json"):
                task.result_json = result
        if error:
            task.error = error
        await db.commit()
        await db.refresh(task)
        websocket_manager.publish(str(task.id), {"type": "status", "status": status_value})
        return task

    async def create_task(
        self,
        db: AsyncSession,
        current_user: object,
        site_id: str,
        task_type: str,
        provider: str,
        payload_data: dict[str, Any],
        enqueue: bool = True,
    ) -> Task:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        normalized_task_type = task_type.strip().lower()
        normalized_provider = provider.strip().lower()
        if normalized_task_type == "deploy":
            normalized_task_type = "deploy_local"
        if normalized_task_type not in SUPPORTED_TASK_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported task_type: {task_type}")
        if normalized_task_type == "develop_code" and normalized_provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
        # Security: strip user-supplied 'command' to prevent arbitrary command execution
        payload_data.pop("command", None)
        task = Task(
            id=str(uuid.uuid4()),
            site_id=site.id,
            project_id=str(site.project_id) if site.project_id else None,
            title=str(payload_data.get("title") or payload_data.get("prompt") or normalized_task_type)[:255],
            description=str(payload_data.get("description") or payload_data.get("prompt") or ""),
            priority=str(payload_data.get("priority") or "medium"),
            assignee=str(payload_data.get("assignee") or ""),
            board_status="queued",
            provider=normalized_provider if normalized_task_type == "develop_code" else "",
            task_type=normalized_task_type,
            status=TaskStatus.QUEUED.value,
            workflow_stages_json=list(payload_data.get("workflow_stages") or []),
            runtime_config_dir=str(Path("/tmp/nextproject-task-runtime") / str(uuid.uuid4())),
        )
        task.runtime_config_dir = str(Path("/tmp/nextproject-task-runtime") / str(task.id))
        task.payload_json = payload_data
        db.add(task)
        repo_root = self._repo_root_for_site(site)
        db.add(TaskRepository(task_id=task.id, site_id=site.id, repo_path=str(repo_root)))
        await db.commit()
        await db.refresh(task)
        await self.append_log(db, task, f"Task created: {normalized_task_type}", source="api")
        if enqueue:
            self.enqueue_task(task)
        return task

    async def create_project_task(
        self,
        db: AsyncSession,
        current_user: object,
        project_id: str,
        payload_data: dict[str, Any],
        enqueue: bool = True,
    ) -> Task:
        project = await project_service.get_project(db, project_id, current_user)
        repo_ids = [str(item).strip() for item in (payload_data.get("repo_ids") or []) if str(item).strip()]
        if not repo_ids:
            raise HTTPException(status_code=400, detail="repo_ids is required")
        sites: list[Site] = []
        for repo_id in repo_ids:
            site = await site_service.get_site_by_public_id(db, repo_id, current_user)
            if str(site.project_id) != str(project.id):
                raise HTTPException(status_code=404, detail=f"Repo not found in project: {repo_id}")
            sites.append(site)
        task_type = str(payload_data.get("task_type") or "develop_code").strip().lower()
        provider = str(payload_data.get("provider") or "codex").strip().lower()
        if task_type != "develop_code":
            raise HTTPException(status_code=400, detail="Project tasks currently support develop_code only")
        if provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
        payload_data.pop("command", None)
        primary_site = sites[0]
        task = Task(
            id=str(uuid.uuid4()),
            site_id=primary_site.id,
            project_id=str(project.id),
            title=str(payload_data.get("title") or payload_data.get("prompt") or "多仓开发任务")[:255],
            description=str(payload_data.get("description") or payload_data.get("prompt") or ""),
            priority=str(payload_data.get("priority") or "medium"),
            assignee=str(payload_data.get("assignee") or ""),
            board_status="queued",
            provider=provider,
            task_type=task_type,
            status=TaskStatus.QUEUED.value,
            workflow_stages_json=list(payload_data.get("workflow_stages") or []),
            runtime_config_dir=str(Path("/tmp/nextproject-task-runtime") / str(uuid.uuid4())),
        )
        task.runtime_config_dir = str(Path("/tmp/nextproject-task-runtime") / str(task.id))
        task.payload_json = {**payload_data, "project_id": str(project.id), "repo_ids": [site.site_id for site in sites]}
        db.add(task)
        for site in sites:
            db.add(TaskRepository(task_id=task.id, site_id=site.id, repo_path=str(self._repo_root_for_site(site))))
        await db.commit()
        await db.refresh(task)
        await self.append_log(db, task, f"Project task created for {len(sites)} repos", source="api")
        if enqueue:
            self.enqueue_task(task)
        return task

    def enqueue_task(self, task: Task) -> None:
        try:
            if task.task_type == "develop_code":
                from backend.tasks.develop_code import develop_code_task

                develop_code_task.delay(str(task.id))
            elif task.task_type in {"deploy_local", "deploy_apollo"}:
                from backend.tasks.deploy import deploy_task

                deploy_task.delay(str(task.id))
            elif task.task_type == "test_local_playwright":
                from backend.tasks.test import smoke_test_task

                smoke_test_task.delay(str(task.id))
            elif task.task_type == "clone_repo":
                from backend.tasks.clone_repo import clone_repo_task

                clone_repo_task.delay(str(task.id))
        except Exception:
            return

    def _run_git(self, repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=check,
            env=self._git_env(),
        )

    def _git_head(self, repo: Path) -> str:
        result = self._run_git(repo, ["rev-parse", "HEAD"], check=False)
        return result.stdout.strip() if result.returncode == 0 else ""

    def _git_dirty(self, repo: Path) -> bool:
        result = self._run_git(repo, ["status", "--porcelain"], check=False)
        return bool(result.stdout.strip())

    def _ensure_git_repo(self, repo: Path) -> None:
        repo.mkdir(parents=True, exist_ok=True)
        if not (repo / ".git").exists():
            self._run_git(repo, ["init"])
        if not self._git_head(repo):
            self._run_git(repo, ["add", "-A"])
            self._run_git(repo, ["commit", "--allow-empty", "-m", "NextProject initial checkpoint"])

    def _commit_if_dirty(self, repo: Path, message: str) -> tuple[str, bool]:
        if not self._git_dirty(repo):
            return self._git_head(repo), False
        self._run_git(repo, ["add", "-A"])
        self._run_git(repo, ["commit", "-m", message])
        return self._git_head(repo), True

    async def prepare_git_checkpoints(self, db: AsyncSession, task: Task) -> list[TaskRepository]:
        rows = await db.execute(select(TaskRepository).where(TaskRepository.task_id == task.id))
        bindings = list(rows.scalars().all())
        for binding in bindings:
            repo = Path(binding.repo_path)
            self._ensure_git_repo(repo)
            pre_message = f"NextProject pre-task checkpoint: {task.id}"
            before_sha, _ = self._commit_if_dirty(repo, pre_message)
            binding.before_sha = before_sha or self._git_head(repo)
            binding.rollback_status = ""
        await db.commit()
        return bindings

    async def finalize_git_checkpoints(self, db: AsyncSession, task: Task) -> list[TaskRepository]:
        rows = await db.execute(select(TaskRepository).where(TaskRepository.task_id == task.id))
        bindings = list(rows.scalars().all())
        summary = (task.title or "task").strip()[:80]
        for binding in bindings:
            repo = Path(binding.repo_path)
            message = f"NextProject task {task.id}: {summary}"
            after_sha, changed = self._commit_if_dirty(repo, message)
            binding.after_sha = after_sha or binding.before_sha
            binding.changed = changed
            binding.commit_message = message if changed else ""
        await db.commit()
        return bindings

    async def rollback_task(self, db: AsyncSession, task_id: str, current_user: object) -> Task:
        task = await self.get_task(db, task_id, current_user)
        rows = await db.execute(select(TaskRepository).where(TaskRepository.task_id == task.id))
        bindings = list(rows.scalars().all())
        if not bindings:
            raise HTTPException(status_code=409, detail="Task has no repository checkpoints")
        for binding in bindings:
            if not binding.before_sha:
                binding.rollback_status = "missing-before-sha"
                continue
            repo = Path(binding.repo_path)
            try:
                self._run_git(repo, ["reset", "--hard", binding.before_sha])
                self._run_git(repo, ["clean", "-fd"])
                binding.rollback_status = "rolled_back"
            except Exception as exc:
                binding.rollback_status = f"failed: {exc}"
        await db.commit()
        await self.append_log(db, task, "已按任务检查点整体回滚所有参与仓库", source="git")
        site_rows = await db.execute(select(Site).where(Site.id.in_([item.site_id for item in bindings])))
        owner_site = site_rows.scalars().first()
        if owner_site is not None:
            owner_ref = self._owner_ref(owner_site)
            for binding in bindings:
                site = await db.get(Site, binding.site_id)
                if site is None:
                    continue
                try:
                    await site_service.restart_site(db, site.site_id, owner_ref)
                except Exception as exc:
                    await self.append_log(db, task, f"{site.name} 回滚后预览重启失败: {exc}", "WARN", source="backend")
        return task

    async def update_board_status(self, db: AsyncSession, task_id: str, current_user: object, board_status: str) -> Task:
        task = await self.get_task(db, task_id, current_user)
        normalized = board_status.strip().lower()
        if normalized not in BOARD_STATUSES:
            raise HTTPException(status_code=400, detail="Unsupported board_status")
        status_val = getattr(task.status, "value", task.status)
        execution_board_status = EXEC_TO_BOARD_STATUS.get(status_val)
        if status_val in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}:
            if normalized == "canceled":
                return await self.cancel_task(db, task_id, current_user)
            if normalized != execution_board_status:
                raise HTTPException(status_code=409, detail="Running task board status is controlled by execution state")
        if normalized in {"queued", "running", "done", "failed", "canceled"} and normalized != execution_board_status:
            raise HTTPException(status_code=409, detail="Execution-linked statuses cannot be set manually")
        task.board_status = normalized
        await db.commit()
        await db.refresh(task)
        websocket_manager.publish(str(task.id), {"type": "board_status", "board_status": normalized})
        return task

    async def get_task_logs(
        self,
        db: AsyncSession,
        task_id: str,
        current_user: object,
        *,
        after_id: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        task = await self.get_task(db, task_id, current_user)
        rows = await db.execute(
            select(TaskLog)
            .where(TaskLog.task_id == task.id, TaskLog.id > after_id)
            .order_by(TaskLog.id.asc())
            .limit(limit)
        )
        return [
            {
                "id": item.id,
                "task_id": str(item.task_id),
                "ts": item.ts.isoformat() if getattr(item, "ts", None) else None,
                "level": item.level,
                "line": item.line,
            }
            for item in rows.scalars().all()
        ]

    async def cancel_task(self, db: AsyncSession, task_id: str, current_user: object) -> Task:
        task = await self.get_task(db, task_id, current_user)
        status_val = getattr(task.status, "value", task.status)
        if status_val in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}:
            await self.update_status(db, task, TaskStatus.CANCELED, error="Canceled by user")
            # 尝试撤销 Celery 任务
            celery_id = getattr(task, "celery_task_id", None)
            if celery_id:
                try:
                    from backend.core.celery_app import celery_app
                    celery_app.control.revoke(celery_id, terminate=True, signal="SIGTERM")
                except Exception:
                    pass
        await self.append_log(db, task, "Cancellation requested", "WARN", source="api")
        return task

    async def delete_task(self, db: AsyncSession, task_id: str, current_user: object) -> None:
        task = await self.get_task(db, task_id, current_user)
        status_val = getattr(task.status, "value", task.status)
        if status_val in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}:
            raise HTTPException(status_code=409, detail="Running tasks cannot be deleted; cancel them first")
        await db.delete(task)
        await db.commit()

    async def run_shell_command(
        self,
        db: AsyncSession,
        task: Task,
        command: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 1800,
        extra_env: dict[str, str] | None = None,
        log_source: str = "shell",
        stream_output_to_logs: bool = True,
        log_command: bool = True,
        command_preview: str | None = None,
        heartbeat_interval_sec: int = 0,
        heartbeat_message: str = "",
        capture_output_path: str | None = None,
    ) -> tuple[int, str]:
        if log_command or command_preview is not None:
            preview = command_preview if command_preview is not None else f"$ {' '.join(command)}"
            await self.append_log(db, task, preview, source=log_source)
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        output_lines: list[str] = []
        capture_path = Path(capture_output_path) if capture_output_path else None
        if capture_path is not None:
            capture_path.parent.mkdir(parents=True, exist_ok=True)
            capture_path.write_text("", encoding="utf-8")
        started_at = monotonic()
        last_heartbeat_at = started_at
        try:
            while True:
                elapsed = monotonic() - started_at
                if elapsed >= timeout_sec:
                    raise TimeoutError(f"Command timed out after {timeout_sec}s")
                wait_timeout = timeout_sec - elapsed
                if heartbeat_interval_sec > 0:
                    wait_timeout = min(wait_timeout, heartbeat_interval_sec)
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=wait_timeout)
                except TimeoutError:
                    if proc.returncode is None and heartbeat_interval_sec > 0:
                        now = monotonic()
                        if now - last_heartbeat_at >= heartbeat_interval_sec and heartbeat_message:
                            await self.append_log(db, task, heartbeat_message, source="backend")
                            last_heartbeat_at = now
                        continue
                    raise
                if not line:
                    break
                text = line.decode("utf-8", "ignore").rstrip()
                output_lines.append(text)
                if capture_path is not None:
                    with capture_path.open("a", encoding="utf-8") as fp:
                        fp.write(text)
                        fp.write("\n")
                if stream_output_to_logs:
                    await self.append_log(db, task, text, source=log_source)
                last_heartbeat_at = monotonic()
            await asyncio.wait_for(proc.wait(), timeout=20)
        except Exception as exc:
            proc.kill()
            await self.append_log(db, task, f"Command execution failed: {exc}", "ERROR", source=log_source)
            raise
        return proc.returncode or 0, "\n".join(output_lines)

    async def run_develop_task(self, db: AsyncSession, task_id: str) -> Task:
        task = await db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
            
        original_provider = task.provider
        supported_providers = ["claude_code", "codex", "gemini_cli"]
        
        # Determine fallback order
        fallback_order = [original_provider]
        for p in supported_providers:
            if p != original_provider:
                fallback_order.append(p)
                
        last_error = None
        for attempt, current_provider in enumerate(fallback_order):
            if attempt > 0:
                await self.append_log(
                    db, 
                    task, 
                    f"Provider {fallback_order[attempt-1]} failed. Attempting failover to {current_provider}...", 
                    source="backend"
                )
                # update task provider for this attempt
                task.provider = current_provider
                await db.commit()
                
            try:
                # Run the actual task execution logic for the current provider
                return await self._run_develop_task_for_provider(db, task_id)
            except Exception as e:
                last_error = e
                await self.append_log(
                    db,
                    task,
                    f"Execution with {current_provider} failed: {e}",
                    "ERROR",
                    source="backend"
                )
                continue
                
        # If we got here, all providers failed
        await self.update_status(db, task, TaskStatus.FAILED, error=str(last_error))
        raise last_error
        
    async def _run_develop_task_for_provider(self, db: AsyncSession, task_id: str) -> Task:
        task = await db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        payload = getattr(task, "payload_json", None) or {}
        provider = task.provider
        command_text = ""  # user-supplied command execution is disabled for security
        base_prompt = (payload.get("prompt") or payload.get("instruction") or "").strip()
        rows = await db.execute(select(TaskRepository).where(TaskRepository.task_id == task.id))
        task_repos = list(rows.scalars().all())
        if not task_repos and task.site_id:
            site = await db.get(Site, task.site_id)
            if site is None:
                raise HTTPException(status_code=404, detail="Task site not found")
            repo_root = self._repo_root_for_site(site)
            binding = TaskRepository(task_id=task.id, site_id=site.id, repo_path=str(repo_root))
            db.add(binding)
            await db.commit()
            task_repos = [binding]
        if not task_repos:
            raise HTTPException(status_code=404, detail="Task repositories not found")
        sites_result = await db.execute(select(Site).where(Site.id.in_([repo.site_id for repo in task_repos])))
        sites = list(sites_result.scalars().all())
        site_map = {str(site.id): site for site in sites}
        primary_site = site_map.get(str(task.site_id)) or sites[0]
        owner_ref = self._owner_ref(primary_site)
        project_root = self._project_root_for_task(task, primary_site)
        project_root.mkdir(parents=True, exist_ok=True)
        project_id = str(task.project_id or primary_site.project_id or "")
        site_db_ids = [str(repo.site_id) for repo in task_repos]

        # 拼接上下文信息
        context_parts: list[str] = []
        context_parts.append("[项目约定]\n默认后端: Python\n默认前端: Vue\n除非本次需求明确说明，否则按以上技术栈进行修改与新增。")
        repo_lines = []
        for repo in task_repos:
            site = site_map.get(str(repo.site_id))
            repo_path = Path(repo.repo_path)
            try:
                rel_path = repo_path.relative_to(project_root).as_posix()
            except Exception:
                rel_path = str(repo_path)
            repo_lines.append(f"- {site.name if site else repo.site_id}: {rel_path} (site_id={site.site_id if site else repo.site_id})")
        context_parts.append("[参与仓库]\n本任务需要在项目根目录下同时协调以下仓库修改：\n" + "\n".join(repo_lines))
        workflow_stages = list(getattr(task, "workflow_stages_json", None) or payload.get("workflow_stages") or [])
        if workflow_stages:
            labels = [WORKFLOW_STAGE_LABELS.get(stage, stage) for stage in workflow_stages]
            context_parts.append("[本次任务阶段要求]\n请按以下阶段组织思考、实现和交付说明：" + "、".join(labels))
        current_url = self._normalize_context_url((payload.get("current_url") or "").strip(), primary_site)
        selected_xpath = (payload.get("selected_xpath") or "").strip()
        console_errors = (payload.get("console_errors") or "").strip()
        if current_url or selected_xpath or console_errors:
            context_parts.append("[系统上下文]")
            if current_url:
                context_parts.append(f"当前页面 URL: {current_url}")
            if selected_xpath:
                context_parts.append(f"选中元素 XPath: {selected_xpath}")
            if console_errors:
                context_parts.append(f"控制台错误:\n{console_errors}")
        selected_mcp_service_ids = [
            str(item).strip()
            for item in (payload.get("mcp_service_ids") or payload.get("enabled_mcp_services") or [])
            if str(item).strip()
        ]
        enabled_mcp_services = await mcp_service.resolve_for_repos(
            db,
            project_id=project_id or None,
            site_ids=site_db_ids,
            selected_service_ids=selected_mcp_service_ids,
        )
        if enabled_mcp_services:
            service_lines = [
                f"- {service['service_id']}: {service['name']} - {service['description']}"
                for service in enabled_mcp_services
            ]
            context_parts.append("[已启用 MCP 服务]\n" + "\n".join(service_lines))
        selected_skill_ids = [
            str(item).strip()
            for item in (payload.get("skill_ids") or payload.get("enabled_skill_ids") or [])
            if str(item).strip()
        ]
        selected_skills = await skill_service.resolve_for_repos(
            db,
            project_id=project_id or None,
            site_ids=site_db_ids,
            selected_skill_ids=selected_skill_ids,
        )
        if selected_skills:
            skill_lines = []
            for skill in selected_skills:
                skill_lines.append(f"## {skill['name']}\n{skill['content']}")
            context_parts.append("[已启用 Skills]\n" + "\n\n".join(skill_lines))
        context_parts.append("[文档要求]\n完成修改任务后，将需求文档目录（docs）下的需求按照模块整理好。")
        if base_prompt:
            context_parts.append(f"[本次需求]\n{base_prompt}")
        prompt = "\n\n".join(context_parts) if context_parts else base_prompt

        # 查询用户 Provider 配置
        extra_env: dict[str, str] = {}
        model_name = ""
        runtime_context_root = Path(task.runtime_config_dir or (Path("/tmp/nextproject-task-runtime") / str(task.id)))
        runtime_context_root.mkdir(parents=True, exist_ok=True)
        task.runtime_config_dir = str(runtime_context_root)
        await db.commit()
        mcp_runtime = self._write_mcp_runtime_configs(runtime_context_root, enabled_mcp_services)
        if provider == "codex":
            extra_env["CODEX_HOME"] = mcp_runtime["codex_home"]
        if enabled_mcp_services:
            extra_env["NEXTPROJECT_MCP_CONFIG_PATH"] = self._write_runtime_file(
                runtime_context_root,
                "mcp-services.json",
                {"services": enabled_mcp_services},
            )
        if selected_skills:
            extra_env["NEXTPROJECT_SKILLS_PATH"] = self._write_runtime_file(
                runtime_context_root,
                "skills.json",
                {"skills": selected_skills},
            )
        extra_env["NEXTPROJECT_TASK_CONTEXT_DIR"] = str(runtime_context_root)
        command: list[str] | None = shlex.split(command_text) if command_text else None
        llm_provider = None
        provider_output_path = self._provider_output_path(task, provider)
        if not command:
            from backend.models.user_llm_provider import UserLLMProvider
            # 根据 provider 类型匹配 format
            format_map = {"codex": "responses", "claude_code": "messages"}
            needed_format = format_map.get(provider)
            if needed_format:
                owner_id = str(primary_site.owner_id) if primary_site else None
                if owner_id:
                    scope_conditions = [UserLLMProvider.scope_type == "global"]
                    if project_id:
                        scope_conditions.append(UserLLMProvider.project_id == project_id)
                    rows = await db.execute(
                        select(UserLLMProvider).where(
                            UserLLMProvider.user_id == owner_id,
                            or_(*scope_conditions),
                        ).order_by(
                            case((UserLLMProvider.project_id == project_id, 0), else_=1) if project_id else case((UserLLMProvider.scope_type == "global", 0), else_=1),
                            UserLLMProvider.is_default.desc(),
                            UserLLMProvider.created_at,
                        )
                    )
                    for candidate in rows.scalars().all():
                        raw_formats = getattr(candidate, "formats_json", None) or []
                        if isinstance(raw_formats, str):
                            raw_formats = [raw_formats]
                        formats = [str(item).strip() for item in raw_formats if str(item).strip()]
                        legacy_format = str(getattr(candidate, "format", "") or "").strip()
                        if legacy_format and legacy_format not in formats:
                            formats.insert(0, legacy_format)
                        if needed_format in formats:
                            llm_provider = candidate
                            break

            if llm_provider and llm_provider.api_key:
                decrypted_key = decrypt_api_key(llm_provider.api_key)
                model_name = (llm_provider.models or [""])[0] if llm_provider.models else ""
                api_key_file = self._write_api_key_file(runtime_context_root, decrypted_key)
                if provider == "codex":
                    extra_env["CODEX_TASK_API_KEY_FILE"] = api_key_file
                    extra_env["CODEX_TASK_HOME"] = mcp_runtime["codex_home"]
                    if llm_provider.base_url:
                        extra_env["CODEX_TASK_OPENAI_BASE_URL"] = llm_provider.base_url
                        codex_config_path = Path(mcp_runtime["codex_home"]) / "config.toml"
                        with codex_config_path.open("a", encoding="utf-8") as fp:
                            fp.write(f'\nopenai_base_url = "{llm_provider.base_url}"\n')
                    cmd_parts = [
                        "sh",
                        "-lc",
                        (
                            'set -e; '
                            'export HOME="${CODEX_TASK_HOME}"; '
                            'export CODEX_HOME="${CODEX_TASK_HOME}"; '
                            'cat "${CODEX_TASK_API_KEY_FILE}" | codex login --with-api-key >/dev/null; '
                            'exec codex exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox "$@"'
                        ),
                        "codex-task",
                    ]
                    if model_name:
                        cmd_parts.extend(["--model", model_name])
                    command = cmd_parts
                elif provider == "claude_code":
                    # Accepted Risk: Claude CLI only supports ANTHROPIC_API_KEY env var,
                    # no file-based alternative exists. The env var is scoped to the
                    # short-lived Celery worker subprocess and destroyed on completion.
                    extra_env["ANTHROPIC_API_KEY"] = decrypted_key
                    if llm_provider.base_url:
                        extra_env["ANTHROPIC_BASE_URL"] = llm_provider.base_url
                    cmd_parts = [os.getenv("CLAUDE_CMD", "claude")]
                    cmd_parts.extend(["--mcp-config", mcp_runtime["claude_mcp_config"], "--strict-mcp-config"])
                    if model_name:
                        cmd_parts.extend(["--model", model_name])
                    cmd_parts.append("-p")
                    command = cmd_parts
            if not command:
                # 回退到环境变量默认命令
                provider_commands = {
                    "codex": os.getenv("CODEX_CMD", "codex exec"),
                    "claude_code": os.getenv("CLAUDE_CMD", "claude"),
                    "gemini_cli": os.getenv("GEMINI_CMD", "gemini"),
                }
                command_text = provider_commands.get(provider, "")
                command = shlex.split(command_text) if command_text else None
                if command and provider == "claude_code":
                    command.extend(["--mcp-config", mcp_runtime["claude_mcp_config"], "--strict-mcp-config"])
        if not command:
            raise HTTPException(status_code=400, detail=f"Missing provider command for {provider}")
        if prompt and not payload.get("command"):
            command.append(prompt)
        await self.prepare_git_checkpoints(db, task)
        await self.update_status(db, task, TaskStatus.RUNNING)
        log_source = provider or "shell"
        await self.append_log(
            db,
            task,
            f"Provider 配置: {llm_provider.name if llm_provider else '环境默认'}",
            source="backend",
        )
        if model_name:
            await self.append_log(db, task, f"模型: {model_name}", source="backend")
        await self.append_log(db, task, f"工作目录: {project_root}", source="backend")
        if current_url:
            await self.append_log(db, task, f"当前页面 URL: {current_url}", source="backend")
        if selected_xpath:
            await self.append_log(db, task, f"选中元素 XPath: {selected_xpath}", source="backend")
        if enabled_mcp_services:
            await self.append_log(
                db,
                task,
                "已启用 MCP 服务: " + ", ".join(service["service_id"] for service in enabled_mcp_services),
                source="backend",
            )
        if selected_skills:
            await self.append_log(
                db,
                task,
                "已启用 Skills: " + ", ".join(skill["name"] for skill in selected_skills),
                source="backend",
            )
        if provider == "codex":
            await self.append_log(
                db,
                task,
                "Codex 已启动。代码 diff 和原始生成内容不会直接显示在任务日志中。",
                source="backend",
            )
            await self.append_log(
                db,
                task,
                "任务运行期间，这里仍会持续显示上下文摘要和进度提示。",
                source="backend",
            )
        exit_code, output = await self.run_shell_command(
            db,
            task,
            command,
            cwd=project_root,
            extra_env=extra_env,
            log_source=log_source,
            stream_output_to_logs=provider != "codex",
            log_command=provider != "codex",
            command_preview=self._safe_command_preview(provider, model_name, command_text) if provider == "codex" else None,
            heartbeat_interval_sec=15 if provider == "codex" else 0,
            heartbeat_message="Codex 正在继续处理本次修改...",
            capture_output_path=str(provider_output_path) if provider == "codex" else None,
        )
        if exit_code != 0:
            if provider == "codex":
                await self.append_log(
                    db,
                    task,
                    f"Codex 执行结束，但退出码为 {exit_code}。详细输出已隐藏。",
                    "WARN",
                    source="backend",
                )
            error_msg = f"CLI exited with {exit_code}"
            await self.update_status(db, task, TaskStatus.FAILED, error=error_msg)
            raise Exception(error_msg)
        if provider == "codex":
            await self.append_log(db, task, "Codex 执行完成", source="backend")
        finalized_repos = await self.finalize_git_checkpoints(db, task)
        restart_result: dict[str, Any] = {"attempted": False, "ok": True}
        try:
            restart_result["attempted"] = True
            await self.append_log(db, task, "开发任务已完成，正在重启参与仓库预览...", source="backend")
            for site in sites:
                try:
                    await site_service.restart_site(db, site.site_id, owner_ref)
                except Exception as exc:
                    await self.append_log(db, task, f"{site.name} 预览重启失败: {exc}", "WARN", source="backend")
            await self.append_log(db, task, "参与仓库预览重启完成", source="backend")
        except Exception as exc:
            restart_result = {"attempted": True, "ok": False, "error": str(exc)}
            await self.append_log(db, task, f"Site preview restart failed: {exc}", "WARN", source="backend")
        await self.update_status(
            db,
            task,
            TaskStatus.SUCCESS,
            result={
                "provider": provider,
                "exit_code": exit_code,
                "output_tail": output[-2000:],
                "provider_output_path": str(provider_output_path) if provider == "codex" else "",
                "preview_restart": restart_result,
                "repositories": [
                    {
                        "site_id": str(repo.site_id),
                        "before_sha": repo.before_sha,
                        "after_sha": repo.after_sha,
                        "changed": bool(repo.changed),
                    }
                    for repo in finalized_repos
                ],
            },
        )
        return task

    async def run_playwright_smoke_task(self, db: AsyncSession, task_id: str) -> Task:
        task = await db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        payload = getattr(task, "payload_json", None) or {}
        site = await db.get(Site, task.site_id)
        await self.update_status(db, task, TaskStatus.RUNNING)
        base_url = (payload.get("base_url") or os.getenv("PLAYWRIGHT_BASE_URL") or "http://127.0.0.1:8080").rstrip("/")
        if Path("/.dockerenv").exists() and base_url.endswith(":18080"):
            base_url = "http://127.0.0.1:8080"
        artifacts_dir = self._task_artifacts_root() / str(task.id)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        script_path = Path("main_service/app/scripts/playwright_smoke_runner.mjs")
        if not script_path.exists():
            script_path = Path("app/scripts/playwright_smoke_runner.mjs")
        command = [
            "node",
            str(script_path),
            "--base-url",
            base_url,
            "--site-id",
            site.site_id,
            "--artifacts-dir",
            str(artifacts_dir),
        ]
        exit_code, output = await self.run_shell_command(db, task, command, log_source="playwright")
        result: dict[str, Any] = {"ok": False, "artifacts_dir": str(artifacts_dir)}
        for line in reversed(output.splitlines()):
            try:
                result = json.loads(line)
                break
            except Exception:
                continue
        if exit_code != 0 or not result.get("ok", False):
            await self.update_status(db, task, TaskStatus.FAILED, result=result, error="Playwright smoke failed")
            return task
        await self.update_status(db, task, TaskStatus.SUCCESS, result=result)
        return task


task_service = TaskService()
