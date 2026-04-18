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
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Site, Task, TaskLog, TaskStatus
from backend.models.workflow import WorkflowRun
from backend.core.encryption import decrypt_api_key
from backend.services.mcp_service import mcp_service
from backend.services.site_service import site_service
from backend.services.skill_service import skill_service
from backend.services.websocket_service import websocket_manager
from backend.services.workflow_service import WORKFLOW_STAGE_LABELS

SUPPORTED_PROVIDERS = {"codex", "claude_code", "gemini_cli"}
SUPPORTED_TASK_TYPES = {"develop_code", "test_local_playwright", "deploy_local", "deploy_apollo", "clone_repo"}
TASK_WORKFLOW_STAGE_RULES = {
    "develop_code": {"execute", "optimize"},
    "test_local_playwright": {"execute", "optimize", "review"},
    "deploy_local": {"execute"},
    "deploy_apollo": {"execute"},
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

    def serialize_task(self, task: Task) -> dict[str, Any]:
        payload = getattr(task, "payload", None) or getattr(task, "payload_json", None) or {}
        result = getattr(task, "result", None) or getattr(task, "result_json", None) or {}
        return {
            "id": str(task.id),
            "site_id": str(getattr(task, "site_id", "")),
            "provider": getattr(task, "provider", ""),
            "task_type": getattr(task, "task_type", ""),
            "status": getattr(getattr(task, "status", ""), "value", getattr(task, "status", "")),
            "payload": payload,
            "result": result,
            "error": getattr(task, "error", ""),
            "created_at": getattr(task, "created_at", None).isoformat() if getattr(task, "created_at", None) else None,
            "started_at": getattr(task, "started_at", None).isoformat() if getattr(task, "started_at", None) else None,
            "finished_at": getattr(task, "finished_at", None).isoformat() if getattr(task, "finished_at", None) else None,
        }

    async def get_task(self, db: AsyncSession, task_id: str, current_user: object) -> Task:
        task = await db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        site = await db.get(Site, task.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Task site not found")
        await site_service.get_site_by_public_id(db, site.site_id, current_user)
        return task

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
    ) -> list[Task]:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        rows = await db.execute(
            select(Task).where(Task.site_id == site.id).order_by(desc(Task.created_at), desc(Task.id)).limit(limit)
        )
        return list(rows.scalars().all())

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
            self._cleanup_task_runtime(str(task.id))
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
        workflow_run_id = str(payload_data.get("workflow_run_id") or "").strip()
        if workflow_run_id:
            run = await db.get(WorkflowRun, workflow_run_id)
            if run is None or str(run.site_id) != str(site.id):
                raise HTTPException(status_code=404, detail="Workflow run not found for this site")
            workflow_stage = str(payload_data.get("workflow_stage") or run.current_stage).strip() or run.current_stage
            allowed = TASK_WORKFLOW_STAGE_RULES.get(normalized_task_type, set())
            if workflow_stage not in allowed:
                raise HTTPException(
                    status_code=409,
                    detail=f"Task type {normalized_task_type} is not allowed in workflow stage {workflow_stage}",
                )
            payload_data["workflow_stage"] = workflow_stage
        # Security: strip user-supplied 'command' to prevent arbitrary command execution
        payload_data.pop("command", None)
        task = Task(
            id=str(uuid.uuid4()),
            site_id=site.id,
            provider=normalized_provider if normalized_task_type == "develop_code" else "",
            task_type=normalized_task_type,
            status=TaskStatus.QUEUED.value,
        )
        task.payload_json = payload_data
        db.add(task)
        await db.commit()
        await db.refresh(task)
        await self.append_log(db, task, f"Task created: {normalized_task_type}", source="api")
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
        task.status = TaskStatus.FAILED
        task.error = str(last_error)
        await db.commit()
        raise last_error
        
    async def _run_develop_task_for_provider(self, db: AsyncSession, task_id: str) -> Task:
        task = await db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        payload = getattr(task, "payload_json", None) or {}
        provider = task.provider
        command_text = ""  # user-supplied command execution is disabled for security
        base_prompt = (payload.get("prompt") or payload.get("instruction") or "").strip()
        site = await db.get(Site, task.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Task site not found")
        owner_ref = self._owner_ref(site)

        # 拼接上下文信息
        context_parts: list[str] = []
        context_parts.append("[项目约定]\n默认后端: Python\n默认前端: Vue\n除非本次需求明确说明，否则按以上技术栈进行修改与新增。")
        current_url = self._normalize_context_url((payload.get("current_url") or "").strip(), site)
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
        workflow_run_id = str(payload.get("workflow_run_id") or "").strip()
        workflow_manifest: dict[str, Any] = {}
        if workflow_run_id:
            workflow_run = await db.get(WorkflowRun, workflow_run_id)
            if workflow_run and str(workflow_run.site_id) == str(site.id):
                workflow_stage = str(payload.get("workflow_stage") or workflow_run.current_stage).strip() or workflow_run.current_stage
                artifact_rel = str((workflow_run.stage_artifacts_json or {}).get(workflow_stage) or "")
                artifact_content = ""
                if artifact_rel:
                    artifact_path = site_service.site_root(site.site_id) / artifact_rel
                    if artifact_path.exists():
                        artifact_content = artifact_path.read_text(encoding="utf-8")
                workflow_manifest = {
                    "run_id": workflow_run_id,
                    "name": workflow_run.name,
                    "stage": workflow_stage,
                    "stage_label": WORKFLOW_STAGE_LABELS.get(workflow_stage, workflow_stage),
                    "artifact_path": artifact_rel,
                    "artifact_content": artifact_content,
                }
                context_parts.append(
                    "[工作流上下文]\n"
                    f"工作流: {workflow_run.name}\n"
                    f"当前阶段: {workflow_manifest['stage_label']}"
                )
                if artifact_content:
                    context_parts.append(f"[当前阶段文档]\n{artifact_content}")
        selected_mcp_service_ids = [str(item).strip() for item in (payload.get("enabled_mcp_services") or []) if str(item).strip()]
        enabled_mcp_services = await mcp_service.get_enabled_services(db, str(site.owner_id), selected_mcp_service_ids)
        if enabled_mcp_services:
            service_lines = [
                f"- {service['service_id']}: {service['name']} - {service['description']}"
                for service in enabled_mcp_services
            ]
            context_parts.append("[已启用 MCP 服务]\n" + "\n".join(service_lines))
        selected_skill_ids = [str(item).strip() for item in (payload.get("enabled_skill_ids") or []) if str(item).strip()]
        selected_skills = await skill_service.get_selected_skills(db, owner_ref, site.site_id, selected_skill_ids)
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
        runtime_context_root = Path("/tmp/nextproject-task-runtime") / str(task.id)
        if workflow_manifest:
            extra_env["NEXTPROJECT_WORKFLOW_PATH"] = self._write_runtime_file(
                runtime_context_root, "workflow.json", workflow_manifest
            )
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
        if not command:
            from backend.models.user_llm_provider import UserLLMProvider
            # 根据 provider 类型匹配 format
            format_map = {"codex": "responses", "claude_code": "messages"}
            needed_format = format_map.get(provider)
            if needed_format:
                owner_id = str(site.owner_id) if site else None
                if owner_id:
                    rows = await db.execute(
                        select(UserLLMProvider).where(
                            UserLLMProvider.user_id == owner_id,
                            UserLLMProvider.format == needed_format,
                        ).order_by(UserLLMProvider.is_default.desc(), UserLLMProvider.created_at)
                    )
                    llm_provider = rows.scalars().first()

            if llm_provider and llm_provider.api_key:
                decrypted_key = decrypt_api_key(llm_provider.api_key)
                model_name = (llm_provider.models or [""])[0] if llm_provider.models else ""
                api_key_file = self._write_api_key_file(runtime_context_root, decrypted_key)
                if provider == "codex":
                    extra_env["CODEX_TASK_API_KEY_FILE"] = api_key_file
                    extra_env["CODEX_TASK_HOME"] = f"/tmp/nextproject-codex/{task.id}"
                    if llm_provider.base_url:
                        extra_env["CODEX_TASK_OPENAI_BASE_URL"] = llm_provider.base_url
                    cmd_parts = [
                        "sh",
                        "-lc",
                        (
                            'set -e; '
                            'export HOME="${CODEX_TASK_HOME}"; '
                            'export CODEX_HOME="${CODEX_TASK_HOME}/.codex"; '
                            'mkdir -p "$CODEX_HOME"; '
                            'printf \'cli_auth_credentials_store = "file"\\n\' > "$CODEX_HOME/config.toml"; '
                            'if [ -n "${CODEX_TASK_OPENAI_BASE_URL:-}" ]; then '
                            'printf \'openai_base_url = "%s"\\n\' "$CODEX_TASK_OPENAI_BASE_URL" >> "$CODEX_HOME/config.toml"; '
                            'fi; '
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
        if not command:
            raise HTTPException(status_code=400, detail=f"Missing provider command for {provider}")
        if prompt and not payload.get("command"):
            command.append(prompt)
        # site 已在上方查询
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
        await self.append_log(db, task, f"工作目录: {site_service.site_root(site.site_id)}", source="backend")
        if current_url:
            await self.append_log(db, task, f"当前页面 URL: {current_url}", source="backend")
        if selected_xpath:
            await self.append_log(db, task, f"选中元素 XPath: {selected_xpath}", source="backend")
        if workflow_manifest:
            await self.append_log(
                db,
                task,
                f"工作流上下文: {workflow_manifest['name']} / {workflow_manifest['stage_label']}",
                source="backend",
            )
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
            provider_output_path = self._provider_output_path(task, provider)
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
            cwd=site_service.site_root(site.site_id),
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
        restart_result: dict[str, Any] = {"attempted": False, "ok": True}
        try:
            if site is not None:
                restart_result["attempted"] = True
                await self.append_log(
                    db,
                    task,
                    "开发任务已完成，正在重启站点预览...",
                    source="backend",
                )
                await site_service.restart_site(
                    db,
                    site.site_id,
                    owner_ref,
                )
                await self.append_log(db, task, "站点预览已重启", source="backend")
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
