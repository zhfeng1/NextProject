from __future__ import annotations

import asyncio
import json
import os
import re
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

import httpx
from fastapi import HTTPException
from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Conversation, Project, Site, Task, TaskLog, TaskRepository, TaskStatus
from backend.models.user_llm_provider import UserLLMProvider
from backend.core.encryption import decrypt_api_key
from backend.services.execution_trace_service import read_execution_trace, redact_execution_text
from backend.services.mcp_service import mcp_service
from backend.services.conversation_git_service import conversation_git_service
from backend.services.project_service import project_service
from backend.services.programming_tool_service import SUPPORTED_TOOL_IDS, programming_tool_service
from backend.services.site_service import site_service
from backend.services.skill_service import skill_service
from backend.services.websocket_service import websocket_manager

SUPPORTED_PROVIDERS = set(SUPPORTED_TOOL_IDS)
SUPPORTED_TASK_TYPES = {
    "develop_code",
    "test_local_playwright",
    "deploy_local",
    "deploy_apollo",
    "deploy_tech_platform",
    "clone_repo",
}
DEFAULT_STACK_PROMPT = "[项目约定]\n默认后端: Python\n默认前端: Vue\n除非本次需求明确说明，否则按以上技术栈进行修改与新增。"
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
ADAPTER_URLS = {
    tool_id: spec.adapter_url
    for tool_id in SUPPORTED_PROVIDERS
    if (spec := programming_tool_service.get_spec(tool_id)) is not None
}
PROVIDER_OUTPUT_BLOCK_SEPARATOR = "\n\x1e\n"


class TaskService:
    @staticmethod
    def _llm_provider_formats(provider: UserLLMProvider) -> list[str]:
        raw_formats = getattr(provider, "formats_json", None) or []
        if isinstance(raw_formats, str):
            raw_formats = [raw_formats]
        formats = [str(item).strip() for item in raw_formats if str(item).strip()]
        legacy_format = str(getattr(provider, "format", "") or "").strip()
        if legacy_format and legacy_format not in formats:
            formats.insert(0, legacy_format)
        return formats

    async def resolve_configured_llm_provider(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        provider: str,
        project_id: str | None = None,
    ) -> UserLLMProvider | None:
        if not project_id:
            return None
        resolved = await programming_tool_service.resolve_project_provider(
            db,
            user_id=str(user_id),
            project_id=str(project_id),
            tool_id=provider,
        )
        return resolved[0] if resolved else None

    async def resolve_configured_tool_provider(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        provider: str,
        project_id: str | None,
    ) -> tuple[UserLLMProvider, str] | None:
        if not project_id:
            return None
        return await programming_tool_service.resolve_project_provider(
            db,
            user_id=str(user_id),
            project_id=str(project_id),
            tool_id=provider,
        )

    async def require_configured_provider(
        self,
        db: AsyncSession,
        *,
        current_user: object,
        provider: str,
        project_id: str | None = None,
    ) -> UserLLMProvider:
        if provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"不支持的编程工具: {provider}")
        if not project_id:
            raise HTTPException(status_code=400, detail="编程任务必须属于已配置模型 Provider 的项目")
        configured, _format = await programming_tool_service.require_project_provider(
            db,
            user_id=str(getattr(current_user, "id")),
            project_id=str(project_id),
            tool_id=provider,
        )
        return configured

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
    def _provider_label(provider: str) -> str:
        return {
            "codex": "Codex",
            "claude_code": "编程工具",
            "codebuddy": "CodeBuddy",
            "opencode": "OpenCode",
            "kimi_code": "Kimi Code",
        }.get(provider, "编程工具" if provider else "System")

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
            return f"执行命令: $ codex exec --json --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox{model_part} [prompt hidden]"
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
        return artifacts_root / str(task.id) / f"{provider_name}-user-output.log"

    @staticmethod
    def _provider_raw_output_path(task: Task, provider: str = "") -> Path:
        provider_name = (provider or getattr(task, "provider", "") or "provider").strip() or "provider"
        artifacts_root = TaskService._task_artifacts_root()
        return artifacts_root / str(task.id) / f"{provider_name}-raw-output.log"

    @staticmethod
    def _execution_trace_path(task: Task, provider: str = "") -> Path:
        provider_name = (provider or getattr(task, "provider", "") or "provider").strip() or "provider"
        artifacts_root = TaskService._task_artifacts_root()
        return artifacts_root / str(task.id) / f"{provider_name}-execution-trace.ndjson"

    @staticmethod
    def _strip_code_blocks(text: str) -> str:
        cleaned = re.sub(r"```[^\n]*\n.*?(?:```|$)", "", text, flags=re.DOTALL)
        cleaned = re.sub(r"~~~[^\n]*\n.*?(?:~~~|$)", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @classmethod
    def _extract_codex_user_message(cls, line: str) -> str:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return ""
        if event.get("type") != "item.completed":
            return ""
        item = event.get("item") or {}
        if item.get("type") != "agent_message":
            return ""
        text = str(item.get("text") or "").strip()
        if not text:
            return ""
        return cls._strip_code_blocks(text)

    @classmethod
    def _recover_codex_output_blocks(cls, raw_path: Path, max_read_bytes: int = 8_000_000) -> str:
        if not raw_path.exists() or not raw_path.is_file():
            return ""
        with raw_path.open("rb") as fp:
            size = raw_path.stat().st_size
            if size > max_read_bytes:
                fp.seek(-max_read_bytes, os.SEEK_END)
                fp.readline()
            raw_text = fp.read().decode("utf-8", errors="ignore")
        blocks = [
            message
            for line in raw_text.splitlines()
            if (message := cls._extract_codex_user_message(line))
        ]
        return PROVIDER_OUTPUT_BLOCK_SEPARATOR.join(blocks)

    @staticmethod
    def _adapter_headers() -> dict[str, str]:
        token = (
            os.getenv("PROGRAMMING_TOOL_ADAPTER_TOKEN", "")
            or os.getenv("PROGRAMMING_ADAPTER_TOKEN", "")
        ).strip()
        return {"X-Adapter-Token": token} if token else {}

    async def _cancel_adapter_run(self, provider: str, task_id: str) -> None:
        adapter_url = ADAPTER_URLS.get(provider)
        if not adapter_url:
            return
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{adapter_url}/v1/runs/{task_id}/cancel",
                    headers=self._adapter_headers(),
                )
        except Exception:
            # Celery termination below remains the final cancellation fallback.
            pass

    async def _run_adapter_stream(
        self,
        db: AsyncSession,
        task: Task,
        *,
        provider: str,
        request_payload: dict[str, Any],
        display_path: Path,
    ) -> tuple[int, str, dict[str, Any]]:
        adapter_url = ADAPTER_URLS.get(provider)
        if not adapter_url:
            raise HTTPException(status_code=400, detail=f"缺少编程工具适配器: {self._provider_label(provider)}")

        display_path.parent.mkdir(parents=True, exist_ok=True)
        display_path.parent.chmod(0o700)
        display_path.write_text("", encoding="utf-8")
        display_path.chmod(0o600)
        display_parts: list[str] = []
        usage: dict[str, Any] = {}
        exit_code: int | None = None
        diagnostic = ""
        canceled = False
        timed_out = False
        native_session_id = ""
        timeout = httpx.Timeout(connect=10, read=None, write=30, pool=10)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{adapter_url}/v1/runs",
                    json=request_payload,
                    headers=self._adapter_headers(),
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="ignore")[:1000]
                        raise RuntimeError(f"适配器请求失败 ({response.status_code}): {body}")
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        event_type = str(event.get("type") or "")
                        if event_type == "display_delta":
                            # Adapters own the stateful code-fence filter because fences
                            # may be split across multiple streamed events.
                            content = str(event.get("content") or "")
                            if not content:
                                continue
                            display_parts.append(content)
                            rendered = "".join(display_parts).strip()
                            display_path.write_text(rendered + ("\n" if rendered else ""), encoding="utf-8")
                            raw = rendered.encode("utf-8")
                            truncated = len(raw) > 512_000
                            if truncated:
                                raw = raw[-512_000:]
                            websocket_manager.publish(str(task.id), {
                                "type": "provider_output",
                                "data": {
                                    "provider": provider,
                                    "available": True,
                                    "content": raw.decode("utf-8", errors="ignore"),
                                    "truncated": truncated,
                                },
                            })
                        elif event_type == "diagnostic":
                            diagnostic = str(event.get("message") or diagnostic)[:2000]
                        elif event_type == "usage" and isinstance(event.get("usage"), dict):
                            usage.update(event["usage"])
                        elif event_type == "run_finished":
                            exit_code = int(event.get("exit_code") or 0)
                            canceled = bool(event.get("canceled", False))
                            timed_out = bool(event.get("timed_out", False))
                            if isinstance(event.get("usage"), dict):
                                usage.update(event["usage"])
                            diagnostic = str(event.get("error") or diagnostic)[:2000]
                            native_session_id = str(event.get("native_session_id") or "").strip()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"编程工具适配器不可用: {exc}") from exc

        if exit_code is None:
            raise RuntimeError("编程工具适配器流意外结束")
        return exit_code, "".join(display_parts).strip(), {
            "usage": usage,
            "diagnostic": diagnostic,
            "canceled": canceled,
            "timed_out": timed_out,
            "native_session_id": native_session_id,
        }

    async def _persist_provider_session_id(
        self,
        db: AsyncSession,
        task: Task,
        native_session_id: str,
    ) -> str:
        normalized = str(native_session_id or "").strip()
        if not normalized:
            return ""
        if len(normalized) > 255 or re.fullmatch(r"[A-Za-z0-9._:-]+", normalized) is None:
            raise RuntimeError("编程工具返回了无效的原生会话 ID")
        conversation_id = str(getattr(task, "conversation_id", "") or "").strip()
        if not conversation_id:
            return normalized
        conv = await db.get(Conversation, conversation_id)
        if conv is None:
            return normalized
        if str(getattr(conv, "provider", "") or "") != str(getattr(task, "provider", "") or ""):
            raise RuntimeError("编程工具原生会话与开发会话工具不匹配")
        existing = str(getattr(conv, "provider_session_id", "") or "").strip()
        if existing and existing != normalized:
            raise RuntimeError("编程工具恢复后返回了不同的原生会话 ID")
        conv.provider_session_id = normalized
        payload = dict(getattr(task, "payload_json", None) or {})
        payload["provider_session_id"] = normalized
        task.payload_json = payload
        await db.commit()
        return normalized

    @staticmethod
    def _repo_root_for_site(site: Site) -> Path:
        if getattr(site, "project_id", None):
            return project_service.repo_root(str(site.project_id), site.name)
        return site_service.site_root(site.site_id)

    @staticmethod
    def _project_root_for_task(
        task: Task,
        primary_site: Site | None = None,
        task_repos: list[TaskRepository] | None = None,
    ) -> Path:
        payload = getattr(task, "payload_json", None) or {}
        workspace_root = str(payload.get("workspace_root") or "").strip()
        completion_mode = bool(payload.get("completion_mode"))
        repositories = list(task_repos or [])
        if not completion_mode and len(repositories) == 1:
            repo_path = str(getattr(repositories[0], "repo_path", "") or "").strip()
            if repo_path:
                return Path(repo_path)
        if workspace_root:
            return Path(workspace_root)
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
            "conversation_id": str(getattr(task, "conversation_id", "") or payload.get("conversation_id") or ""),
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
        content = output_path.read_text(encoding="utf-8", errors="ignore") if output_path.exists() else ""
        if task.provider == "codex" and "\x1e" not in content:
            recovered = self._recover_codex_output_blocks(self._provider_raw_output_path(task))
            if recovered:
                content = recovered
        if not content:
            return {
                "task_id": str(task.id),
                "provider": task.provider,
                "available": False,
                "content": "",
                "truncated": False,
            }
        raw = content.encode("utf-8")
        truncated = len(raw) > max_bytes
        if truncated:
            raw = raw[-max_bytes:]
        return {
            "task_id": str(task.id),
            "provider": task.provider,
            "available": True,
            "content": raw.decode("utf-8", errors="ignore"),
            "truncated": truncated,
        }

    async def get_task_execution_details(
        self,
        db: AsyncSession,
        task_id: str,
        current_user: object,
        *,
        after_log_id: int = 0,
        after_trace_seq: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        task = await self.get_task(db, task_id, current_user)
        log_rows = await db.execute(
            select(TaskLog)
            .where(TaskLog.task_id == task.id, TaskLog.id > after_log_id)
            .order_by(TaskLog.id.asc())
            .limit(limit + 1)
        )
        backend_logs = list(log_rows.scalars().all())
        backend_has_more = len(backend_logs) > limit
        backend_events = [
            {
                "source": "backend",
                "seq": int(item.id),
                "ts": item.ts.isoformat() if getattr(item, "ts", None) else "",
                "level": str(item.level or "INFO").upper(),
                "kind": "task_log",
                "content": redact_execution_text(item.line),
            }
            for item in backend_logs[:limit]
        ]
        trace_events, trace_has_more = read_execution_trace(
            self._execution_trace_path(task),
            after_seq=after_trace_seq,
            limit=limit,
        )

        candidates = sorted(
            [*backend_events, *trace_events],
            key=lambda item: (
                str(item.get("ts") or ""),
                0 if item.get("source") == "backend" else 1,
                int(item.get("seq") or 0),
            ),
        )
        events = candidates[:limit]
        included_backend = [item for item in events if item.get("source") == "backend"]
        included_trace = [item for item in events if item.get("source") == "adapter"]
        next_log_id = max(
            [after_log_id, *[int(item.get("seq") or 0) for item in included_backend]]
        )
        next_trace_seq = max(
            [after_trace_seq, *[int(item.get("seq") or 0) for item in included_trace]]
        )
        has_more = (
            backend_has_more
            or trace_has_more
            or len(candidates) > len(events)
        )
        status_value = getattr(task.status, "value", task.status)
        terminal = status_value in {
            TaskStatus.SUCCESS.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELED.value,
        }
        return {
            "task_id": str(task.id),
            "events": events,
            "next_after_log_id": next_log_id,
            "next_after_trace_seq": next_trace_seq,
            "has_more": has_more,
            "complete": bool(terminal and not has_more),
            "redacted": True,
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
            raise HTTPException(status_code=400, detail=f"不支持的编程工具: {provider}")
        if normalized_task_type == "develop_code":
            await self.require_configured_provider(
                db,
                current_user=current_user,
                provider=normalized_provider,
                project_id=str(site.project_id) if site.project_id else None,
            )
        # Security: strip user-supplied 'command' to prevent arbitrary command execution
        payload_data.pop("command", None)
        task = Task(
            id=str(uuid.uuid4()),
            site_id=site.id,
            project_id=str(site.project_id) if site.project_id else None,
            conversation_id=str(payload_data.get("conversation_id") or "") or None,
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
        conversation_id = str(payload_data.get("conversation_id") or "").strip()
        completion_mode = bool(payload_data.get("completion_mode"))
        conversation = await db.get(Conversation, conversation_id) if conversation_id else None
        if conversation_id:
            if conversation is None or str(conversation.project_id or "") != str(project.id):
                raise HTTPException(status_code=404, detail="Conversation not found in project")
            conversation_repo_ids = list(getattr(conversation, "repo_ids_json", None) or [])
            if set(conversation_repo_ids) != set(repo_ids):
                raise HTTPException(status_code=409, detail="Task repositories do not match conversation worktree")
        task_type = str(payload_data.get("task_type") or "develop_code").strip().lower()
        provider = str(payload_data.get("provider") or "codex").strip().lower()
        if task_type != "develop_code":
            raise HTTPException(status_code=400, detail="Project tasks currently support develop_code only")
        if provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"不支持的编程工具: {provider}")
        await self.require_configured_provider(
            db,
            current_user=current_user,
            provider=provider,
            project_id=str(project.id),
        )
        payload_data.pop("command", None)
        primary_site = sites[0]
        task = Task(
            id=str(uuid.uuid4()),
            site_id=primary_site.id,
            project_id=str(project.id),
            conversation_id=conversation_id or None,
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
        workspace_root = ""
        conversation_repo_paths: dict[str, str] = {}
        if conversation is not None and not completion_mode:
            workspace_root = str(getattr(conversation, "worktree_root", "") or "")
            conversation_repo_paths = {
                str(item.get("site_id")): str(item.get("worktree_path") or "")
                for item in (getattr(conversation, "git_repos_json", None) or [])
            }
            if not workspace_root or any(not conversation_repo_paths.get(site.site_id) for site in sites):
                raise HTTPException(status_code=409, detail="Conversation worktree is incomplete")
        elif completion_mode:
            workspace_root = str(project_service.project_root(str(project.id)))
        task.payload_json = {
            **payload_data,
            "project_id": str(project.id),
            "repo_ids": [site.site_id for site in sites],
            "workspace_root": workspace_root,
            "branch_name": getattr(conversation, "branch_name", "") if conversation is not None else "",
        }
        db.add(task)
        for site in sites:
            repo_path = (
                conversation_repo_paths.get(site.site_id)
                if conversation is not None and not completion_mode
                else str(self._repo_root_for_site(site))
            )
            db.add(TaskRepository(task_id=task.id, site_id=site.id, repo_path=str(repo_path)))
        await db.commit()
        await db.refresh(task)
        await self.append_log(db, task, f"Project task created for {len(sites)} repos", source="api")
        if enqueue:
            self.enqueue_task(task)
        return task

    def _is_blank_repo_site(self, site: Site) -> bool:
        config = getattr(site, "config", {}) or {}
        source_type = str(config.get("source_type") or "").strip().lower()
        starter = str(config.get("starter") or "").strip().lower()
        if source_type in {"git", "starter"} or starter:
            return False
        return source_type in {"", "legacy", "blank", "empty"}

    async def _should_include_default_stack_prompt(
        self,
        db: AsyncSession,
        task: Task,
        sites: list[Site],
    ) -> bool:
        if getattr(task, "task_type", "") != "develop_code" or not sites:
            return False
        if not all(self._is_blank_repo_site(site) for site in sites):
            return False

        site_ids = [str(site.id) for site in sites]
        previous_rows = await db.execute(
            select(func.count(func.distinct(Task.id)))
            .join(TaskRepository, TaskRepository.task_id == Task.id)
            .where(
                Task.task_type == "develop_code",
                Task.id != task.id,
                TaskRepository.site_id.in_(site_ids),
            )
        )
        return int(previous_rows.scalar_one() or 0) == 0

    def enqueue_task(self, task: Task, *, raise_on_error: bool = False) -> bool:
        try:
            if task.task_type == "develop_code":
                from backend.tasks.develop_code import develop_code_task

                develop_code_task.delay(str(task.id))
            elif task.task_type in {"deploy_local", "deploy_apollo"}:
                from backend.tasks.deploy import deploy_task

                deploy_task.delay(str(task.id))
            elif task.task_type == "deploy_tech_platform":
                from backend.tasks.deploy import tech_platform_deploy_task

                tech_platform_deploy_task.delay(str(task.id))
            elif task.task_type == "test_local_playwright":
                from backend.tasks.test import smoke_test_task

                smoke_test_task.delay(str(task.id))
            elif task.task_type == "clone_repo":
                from backend.tasks.clone_repo import clone_repo_task

                clone_repo_task.delay(str(task.id))
            return True
        except Exception:
            if raise_on_error:
                raise
            return False

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
            after_sha, committed = self._commit_if_dirty(repo, message)
            binding.after_sha = after_sha or binding.before_sha
            binding.changed = committed or binding.after_sha != binding.before_sha
            binding.commit_message = message if committed else ""
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
            await self._cancel_adapter_run(str(task.provider or ""), str(task.id))
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

    async def retry_task(self, db: AsyncSession, task_id: str, current_user: object) -> Task:
        task = await self.get_task(db, task_id, current_user)
        status_val = getattr(task.status, "value", task.status)
        if status_val in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}:
            raise HTTPException(status_code=409, detail="任务正在执行中，不能重试")
        if status_val not in {TaskStatus.FAILED.value, TaskStatus.CANCELED.value}:
            raise HTTPException(status_code=409, detail="只有失败或已取消的任务可以重试")
        if task.task_type == "develop_code":
            await self.require_configured_provider(
                db,
                current_user=current_user,
                provider=task.provider,
                project_id=str(task.project_id) if task.project_id else None,
            )

        task.status = TaskStatus.QUEUED.value
        task.board_status = EXEC_TO_BOARD_STATUS[TaskStatus.QUEUED.value]
        task.error = ""
        task.started_at = None
        task.finished_at = None
        task.celery_task_id = ""
        await db.commit()
        await db.refresh(task)
        await self.append_log(db, task, "Retry requested", "WARN", source="api")
        websocket_manager.publish(str(task.id), {"type": "status", "status": TaskStatus.QUEUED.value})
        self.enqueue_task(task)
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
        display_output_path: str | None = None,
        extract_codex_user_output: bool = False,
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
        display_path = Path(display_output_path) if display_output_path else None
        if display_path is not None:
            display_path.parent.mkdir(parents=True, exist_ok=True)
            display_path.write_text("", encoding="utf-8")
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
                if extract_codex_user_output and display_path is not None:
                    display_text = self._extract_codex_user_message(text)
                    if display_text:
                        with display_path.open("a", encoding="utf-8") as fp:
                            if display_path.stat().st_size:
                                fp.write("\n\n")
                            fp.write(display_text)
                            fp.write("\n")
                        display_raw = display_path.read_bytes()
                        display_truncated = len(display_raw) > 512_000
                        if display_truncated:
                            display_raw = display_raw[-512_000:]
                        websocket_manager.publish(str(task.id), {
                            "type": "provider_output",
                            "data": {
                                "provider": "codex",
                                "available": True,
                                "content": display_raw.decode("utf-8", errors="ignore"),
                                "truncated": display_truncated,
                            },
                        })
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

        provider = task.provider
        try:
            return await self._run_develop_task_for_provider(db, task_id)
        except Exception as exc:
            if await self._preserve_canceled_task(db, task):
                return task
            await self._mark_conversation_completion_failed(db, task, str(exc))
            await self.append_log(
                db,
                task,
                f"{self._provider_label(provider)} 执行失败: {exc}",
                "ERROR",
                source="backend",
            )
            await self.update_status(db, task, TaskStatus.FAILED, error=str(exc))
            raise

    async def _preserve_canceled_task(
        self,
        db: AsyncSession,
        task: Task,
        adapter_result: dict[str, Any] | None = None,
    ) -> bool:
        """Keep an acknowledged adapter cancellation from being rewritten as failed."""
        await db.refresh(task)
        status_value = getattr(task.status, "value", task.status)
        adapter_canceled = bool((adapter_result or {}).get("canceled", False))
        if status_value != TaskStatus.CANCELED.value and not adapter_canceled:
            return False
        if status_value != TaskStatus.CANCELED.value:
            await self.update_status(db, task, TaskStatus.CANCELED, error="Canceled by user")
        await self._mark_conversation_completion_failed(db, task, "任务已取消")
        await self.append_log(
            db,
            task,
            f"{self._provider_label(str(task.provider or ''))} 任务已取消",
            "WARN",
            source="backend",
        )
        return True

    async def _mark_conversation_completion_failed(self, db: AsyncSession, task: Task, error: str) -> None:
        payload = getattr(task, "payload_json", None) or {}
        conv_id = str(payload.get("completion_conversation_id") or "").strip()
        if not conv_id:
            return
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            return
        conv.completion_status = "failed"
        conv.completion_error = error[:2000]
        await db.commit()

    async def _mark_conversation_completed(self, db: AsyncSession, task: Task) -> dict[str, Any]:
        payload = getattr(task, "payload_json", None) or {}
        conv_id = str(payload.get("completion_conversation_id") or "").strip()
        if not conv_id:
            return {}
        from backend.services.conversation_service import conversation_service

        async with conversation_service._lifecycle_lock(conv_id):
            conv = await db.get(Conversation, conv_id)
            if conv is None:
                raise RuntimeError("Completion conversation no longer exists")
            git_repos = list(getattr(conv, "git_repos_json", None) or [])
            try:
                git_repos = conversation_git_service.verify_completed_repositories(git_repos)
                remote_auth = await conversation_service._git_remote_auth(db, git_repos)
                git_repos = conversation_git_service.push_completed_repositories(
                    git_repos,
                    remote_auth=remote_auth,
                )
            except Exception as exc:
                conv.git_repos_json = [dict(item) for item in git_repos]
                conv.completion_status = "failed"
                conv.completion_error = redact_execution_text(str(exc))[:2000]
                await db.commit()
                raise
            conv.git_repos_json = git_repos
            conv.completion_status = "completed"
            conv.completion_error = ""
            conv.completed_at = datetime.now(timezone.utc)
            await db.commit()
            cleanup_exception = False
            try:
                conv = await conversation_service.cleanup_completed_conversation(db, conv_id)
            except Exception as exc:
                cleanup_exception = True
                await db.rollback()
                conv = await db.get(Conversation, conv_id)
                if conv is not None:
                    conv.cleanup_status = "warning"
                    conv.cleanup_error = str(exc)[:4000]
                    await db.commit()
                await self.append_log(
                    db,
                    task,
                    f"会话分支已合并，但自动清理失败: {exc}",
                    "WARN",
                    source="git",
                )
            if conv is None:
                return {"status": "warning", "error": "Conversation cleanup state is unavailable"}
            if getattr(conv, "cleanup_status", "") != "cleaned" and not cleanup_exception:
                await self.append_log(
                    db,
                    task,
                    f"会话分支已合并，清理未完全完成: {getattr(conv, 'cleanup_error', '') or '请重试清理'}",
                    "WARN",
                    source="git",
                )
            return {
                "status": getattr(conv, "cleanup_status", "") or "retained",
                "error": getattr(conv, "cleanup_error", "") or "",
            }
        
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
        project_root = self._project_root_for_task(task, primary_site, task_repos)
        project_root.mkdir(parents=True, exist_ok=True)
        project_id = str(task.project_id or primary_site.project_id or "")
        site_db_ids = [str(repo.site_id) for repo in task_repos]

        # 拼接上下文信息
        context_parts: list[str] = []
        if await self._should_include_default_stack_prompt(db, task, sites):
            context_parts.append(DEFAULT_STACK_PROMPT)
        repo_lines = []
        for repo in task_repos:
            site = site_map.get(str(repo.site_id))
            repo_path = Path(repo.repo_path)
            try:
                rel_path = repo_path.relative_to(project_root).as_posix()
            except Exception:
                rel_path = str(repo_path)
            repo_lines.append(f"- {site.name if site else repo.site_id}: {rel_path} (site_id={site.site_id if site else repo.site_id})")
        if len(task_repos) == 1 and not bool(payload.get("completion_mode")):
            repo_name = site_map.get(str(task_repos[0].site_id))
            context_parts.append(
                "[参与仓库]\n"
                f"当前工作目录就是唯一参与仓库 {repo_name.name if repo_name else task_repos[0].site_id} 的根目录。"
                "所有新增和修改都必须位于当前仓库内，不要在父目录或会话 worktree 根目录创建文件。\n"
                + "\n".join(repo_lines)
            )
        else:
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
        if not bool(payload.get("completion_mode")):
            context_parts.append("[文档要求]\n完成修改任务后，将需求文档目录（docs）下的需求按照模块整理好。")
        if base_prompt:
            context_parts.append(f"[本次需求]\n{base_prompt}")
        prompt = "\n\n".join(context_parts) if context_parts else base_prompt

        owner_id = str(primary_site.owner_id) if primary_site else ""
        resolved_provider = await self.resolve_configured_tool_provider(
            db,
            user_id=owner_id,
            provider=provider,
            project_id=project_id or None,
        )
        if resolved_provider is None:
            await programming_tool_service.require_project_provider(
                db,
                user_id=owner_id,
                project_id=project_id,
                tool_id=provider,
            )
            raise RuntimeError("Provider resolution failed")
        llm_provider, api_format = resolved_provider
        decrypted_key = decrypt_api_key(llm_provider.api_key)
        model_name = programming_tool_service.provider_model(llm_provider)
        provider_output_path = self._provider_output_path(task, provider)
        await self.prepare_git_checkpoints(db, task)
        await self.update_status(db, task, TaskStatus.RUNNING)
        await self.append_log(
            db,
            task,
            f"编程工具配置: {llm_provider.name} · {api_format} · "
            f"{'项目级' if str(llm_provider.scope_type or '') == 'project' else '全局'}",
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
        await self.append_log(
            db,
            task,
            f"{self._provider_label(provider)} 已启动。AI 输出区域会实时显示面向用户的说明。",
            source="backend",
        )
        exit_code, output, adapter_result = await self._run_adapter_stream(
            db,
            task,
            provider=provider,
            request_payload={
                "task_id": str(task.id),
                "conversation_id": (
                    ""
                    if payload.get("completion_mode")
                    else str(getattr(task, "conversation_id", "") or payload.get("conversation_id") or "")
                ),
                "native_session_id": (
                    "" if payload.get("completion_mode") else str(payload.get("provider_session_id") or "")
                ),
                "cwd": str(project_root),
                "prompt": prompt,
                "task_mode": "completion" if payload.get("completion_mode") else "develop",
                "model": {
                    "format": api_format,
                    "base_url": str(llm_provider.base_url or ""),
                    "api_key": decrypted_key,
                    "model": model_name,
                },
                "mcp_servers": enabled_mcp_services,
                "timeout_seconds": 1800,
            },
            display_path=provider_output_path,
        )
        native_session_id = ""
        if not payload.get("completion_mode"):
            native_session_id = await self._persist_provider_session_id(
                db,
                task,
                str(adapter_result.get("native_session_id") or ""),
            )
        if await self._preserve_canceled_task(db, task, adapter_result):
            return task
        if exit_code != 0:
            await self.append_log(
                db,
                task,
                f"{self._provider_label(provider)} 执行结束，但退出码为 {exit_code}。可展开执行日志查看详情。",
                "WARN",
                source="backend",
            )
            error_msg = adapter_result.get("diagnostic") or f"CLI exited with {exit_code}"
            await self.update_status(db, task, TaskStatus.FAILED, error=error_msg)
            raise Exception(error_msg)
        await self.append_log(db, task, f"{self._provider_label(provider)} 执行完成", source="backend")
        finalized_repos = await self.finalize_git_checkpoints(db, task)
        conversation_cleanup = await self._mark_conversation_completed(db, task)
        restart_result: dict[str, Any] = {"attempted": False, "ok": True}
        is_worktree_task = bool(payload.get("workspace_root")) and not bool(payload.get("completion_mode"))
        if is_worktree_task:
            await self.append_log(db, task, "修改已保存在会话 worktree；合并会话后主预览才会更新", source="backend")
        else:
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
                "output_tail": (
                    provider_output_path.read_text(encoding="utf-8", errors="ignore")[-2000:]
                    if provider_output_path.exists()
                    else output[-2000:]
                ),
                "provider_output_path": str(provider_output_path),
                "usage": adapter_result.get("usage") or {},
                "provider_session_id": native_session_id,
                "conversation_cleanup": conversation_cleanup,
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
