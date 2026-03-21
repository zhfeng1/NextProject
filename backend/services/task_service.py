from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Site, Task, TaskLog, TaskStatus
from backend.services.site_service import site_service
from backend.services.websocket_service import websocket_manager

SUPPORTED_PROVIDERS = {"codex", "claude_code", "gemini_cli"}
SUPPORTED_TASK_TYPES = {"develop_code", "test_local_playwright", "deploy_local", "deploy_apollo"}


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
        websocket_manager.publish(str(task.id), {"type": "log", "data": {"level": level, "line": entry.line}})

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
    ) -> tuple[int, str]:
        await self.append_log(db, task, f"$ {' '.join(command)}", source=log_source)
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
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_sec)
                if not line:
                    break
                text = line.decode("utf-8", "ignore").rstrip()
                output_lines.append(text)
                if stream_output_to_logs:
                    await self.append_log(db, task, text, source=log_source)
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
        payload = getattr(task, "payload_json", None) or {}
        provider = task.provider
        command_text = (payload.get("command") or "").strip()
        base_prompt = (payload.get("prompt") or payload.get("instruction") or "").strip()
        site = await db.get(Site, task.site_id)

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
        context_parts.append("[文档要求]\n完成修改任务后，将需求文档目录（docs）下的需求按照模块整理好。")
        if base_prompt:
            context_parts.append(f"[本次需求]\n{base_prompt}")
        prompt = "\n\n".join(context_parts) if context_parts else base_prompt

        # 查询用户 Provider 配置
        extra_env: dict[str, str] = {}
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
                model_name = (llm_provider.models or [""])[0] if llm_provider.models else ""
                if provider == "codex":
                    extra_env["CODEX_TASK_API_KEY"] = llm_provider.api_key
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
                            'printf %s "${CODEX_TASK_API_KEY}" | codex login --with-api-key >/dev/null; '
                            'exec codex exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox "$@"'
                        ),
                        "codex-task",
                    ]
                    if model_name:
                        cmd_parts.extend(["--model", model_name])
                    command = cmd_parts
                elif provider == "claude_code":
                    extra_env["ANTHROPIC_API_KEY"] = llm_provider.api_key
                    if llm_provider.base_url:
                        extra_env["ANTHROPIC_BASE_URL"] = llm_provider.base_url
                    cmd_parts = [os.getenv("CLAUDE_CMD", "claude")]
                    if model_name:
                        cmd_parts.extend(["--model", model_name])
                    cmd_parts.append("-p")  # print mode, non-interactive
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
            f"Provider config: {llm_provider.name if llm_provider else 'env default'}",
            source="backend",
        )
        if provider == "codex":
            await self.append_log(
                db,
                task,
                "Codex is running. Detailed code output is hidden from the task log.",
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
        )
        if exit_code != 0:
            if provider == "codex":
                await self.append_log(
                    db,
                    task,
                    f"Codex finished with a non-zero exit code: {exit_code}. Detailed output is hidden from the task log.",
                    "WARN",
                    source="backend",
                )
            await self.update_status(db, task, TaskStatus.FAILED, error=f"CLI exited with {exit_code}")
            return task
        if provider == "codex":
            await self.append_log(db, task, "Codex execution finished", source="backend")
        restart_result: dict[str, Any] = {"attempted": False, "ok": True}
        try:
            if site is not None:
                restart_result["attempted"] = True
                await self.append_log(
                    db,
                    task,
                    "Development task completed, restarting site preview...",
                    source="backend",
                )
                await site_service.restart_site(
                    db,
                    site.site_id,
                    type(
                        "UserRef",
                        (),
                        {"id": site.owner_id, "default_org_id": site.org_id, "is_superuser": True},
                    )(),
                )
                await self.append_log(db, task, "Site preview restarted", source="backend")
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
        artifacts_dir = Path(os.getenv("TASK_ARTIFACTS_ROOT", "data/task_artifacts")) / str(task.id)
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
