from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tempfile
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Any, BinaryIO, TextIO

from fastapi import HTTPException

from .adapters import ProgrammingToolAdapter
from .models import RunRequest
from .output import StreamingSecretRedactor, StructuredOutputParser
from .trace import ExecutionTraceWriter


def ndjson(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def classify_cli_error(line: str) -> tuple[int, str] | None:
    """Map known CLI/provider failures to safe, user-actionable diagnostics."""
    candidate = line
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        event = None
    if isinstance(event, dict):
        event_type = str(event.get("type") or "")
        if event_type == "turn.failed":
            error = event.get("error")
            candidate = str(error.get("message") or "") if isinstance(error, dict) else str(error or "")
        elif event_type == "error":
            candidate = str(event.get("message") or "")
        elif event_type == "item.completed" and isinstance(event.get("item"), dict):
            item = event["item"]
            if item.get("type") != "error":
                return None
            candidate = str(item.get("message") or "")
        else:
            return None

    normalized = candidate.lower()
    if "invalid token" in normalized or ("401" in normalized and "unauthorized" in normalized):
        return 30, "Provider 认证失败，请检查项目模型配置中的 API Key"
    if any(phrase in normalized for phrase in (
        "unsupported model",
        "model_not_found",
        "model not found",
        "does not support the model",
        "does not support model",
    )):
        return 20, "Provider 不支持所选模型，请检查项目模型配置中的模型名称"
    if "404" in normalized and any(phrase in normalized for phrase in (
        "invalid url",
        "/responses",
        "/messages",
        "/chat/completions",
        "not found",
    )):
        return 10, "Provider 接口不可用，请检查 Base URL 与启用的接口类型"
    return None


@dataclass
class RunSession:
    request: RunRequest
    cwd: Path
    process: asyncio.subprocess.Process | None = None
    cancel_requested: bool = False
    timed_out: bool = False


class RunManager:
    def __init__(self, adapter: ProgrammingToolAdapter) -> None:
        self.adapter = adapter
        self.workspace_root = Path(os.getenv("WORKSPACE_ROOT", "/generated_sites")).resolve()
        self.artifacts_root = Path(os.getenv("TASK_ARTIFACTS_ROOT", "/shared/task_artifacts"))
        self.runtime_root = Path(os.getenv("ADAPTER_RUNTIME_ROOT", "/run/nextproject-adapter"))
        self.sessions: dict[str, RunSession] = {}
        self.lock = asyncio.Lock()

    def validate_cwd(self, raw_cwd: str) -> Path:
        path = Path(raw_cwd)
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.workspace_root)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="cwd must be an existing path under /generated_sites") from exc
        if not resolved.is_dir():
            raise HTTPException(status_code=400, detail="cwd must be a directory")
        return resolved

    def _artifact_dir(self, task_id: str) -> Path:
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        artifacts_root = self.artifacts_root.resolve(strict=True)
        task_dir = artifacts_root / task_id
        task_dir.mkdir(mode=0o700, exist_ok=True)
        try:
            resolved = task_dir.resolve(strict=True)
            resolved.relative_to(artifacts_root)
        except (OSError, ValueError) as exc:
            raise RuntimeError("task artifact directory escapes TASK_ARTIFACTS_ROOT") from exc
        if task_dir.is_symlink() or not resolved.is_dir():
            raise RuntimeError("task artifact path must be a directory")
        resolved.chmod(0o700)
        return resolved

    @staticmethod
    def _open_private_binary(path: Path) -> BinaryIO:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            return os.fdopen(descriptor, "wb")
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _open_private_text(path: Path) -> TextIO:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            return os.fdopen(descriptor, "w", encoding="utf-8")
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _sensitive_values(request: RunRequest) -> tuple[str, ...]:
        values = {request.model_settings.api_key.get_secret_value()}

        def collect(value: Any, key: str = "") -> None:
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    collect(child_value, str(child_key).lower())
            elif isinstance(value, list):
                for child_value in value:
                    collect(child_value, key)
            elif isinstance(value, str) and len(value) >= 4 and any(
                marker in key for marker in ("key", "token", "secret", "password", "authorization")
            ):
                values.add(value)
                if "authorization" in key and value.lower().startswith("bearer "):
                    bearer_token = value[7:].strip()
                    if bearer_token:
                        values.add(bearer_token)

        for service in request.mcp_services:
            collect(service.config)
        return tuple(value for value in values if value)

    async def reserve(self, request: RunRequest) -> RunSession:
        cwd = self.validate_cwd(request.cwd)
        self.adapter.validate_format(request.model_settings.api_format)
        session = RunSession(request=request, cwd=cwd)
        async with self.lock:
            if request.task_id in self.sessions:
                raise HTTPException(status_code=409, detail="task is already running")
            self.sessions[request.task_id] = session
        return session

    async def cancel(self, task_id: str) -> dict[str, Any]:
        async with self.lock:
            session = self.sessions.get(task_id)
            if session is None:
                return {"ok": True, "canceled": False, "message": "task is not running"}
            process = session.process
            if process and process.returncode is not None:
                return {"ok": True, "canceled": False, "message": "task is finishing"}
            session.cancel_requested = True
        if process and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            asyncio.create_task(self._force_kill_after_timeout(process))
        return {"ok": True, "canceled": True}

    @staticmethod
    async def _force_kill_after_timeout(process: asyncio.subprocess.Process) -> None:
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=5)

    async def _unregister(self, task_id: str) -> None:
        async with self.lock:
            self.sessions.pop(task_id, None)

    async def _timeout_run(self, session: RunSession) -> None:
        await asyncio.sleep(session.request.timeout_seconds)
        if session.process and session.process.returncode is not None:
            return
        session.timed_out = True
        process = session.process
        if process and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            asyncio.create_task(self._force_kill_after_timeout(process))

    async def stream(self, session: RunSession) -> AsyncIterator[bytes]:
        request = session.request
        task_dir = self._artifact_dir(request.task_id)
        raw_path = task_dir / f"{self.adapter.spec.tool_id}-raw-output.log"
        display_path = task_dir / f"{self.adapter.spec.tool_id}-user-output.log"
        trace_path = task_dir / f"{self.adapter.spec.tool_id}-execution-trace.ndjson"
        runtime_parent = self.runtime_root
        runtime_parent.mkdir(parents=True, exist_ok=True)
        runtime_dir = Path(tempfile.mkdtemp(prefix=f"{request.task_id}-", dir=runtime_parent))
        runtime_dir.chmod(0o700)
        parser: StructuredOutputParser | None = None
        raw_redactor: StreamingSecretRedactor | None = None
        adapter_stack = AsyncExitStack()
        exit_code = -1
        canceled = False
        error = ""
        classified_error = ""
        classified_error_priority = 0
        usage: dict[str, Any] = {}
        raw_file = None
        display_file = None
        trace_writer: ExecutionTraceWriter | None = None
        stream_aborted = False
        timeout_task = asyncio.create_task(self._timeout_run(session))
        try:
            trace_writer = ExecutionTraceWriter(trace_path, self._sensitive_values(request))
            trace_writer.write("run_context", {
                "prompt": request.prompt,
                "cwd": str(session.cwd),
                "conversation_id": request.conversation_id,
                "native_session_id": request.native_session_id,
                "model": {
                    "format": request.model_settings.api_format,
                    "base_url": request.model_settings.base_url,
                    "model": request.model_settings.model,
                    "provider_name": request.model_settings.provider_name,
                },
                "mcp_servers": [
                    {
                        "service_id": service.service_id,
                        "name": service.name,
                        "description": service.description,
                        "config": service.config,
                    }
                    for service in request.mcp_services
                ],
                "task_mode": request.mode,
            })
            adapter_context = await adapter_stack.enter_async_context(self.adapter.run_context(request))
            trace_writer.add_sensitive_values(adapter_context.sensitive_values)
            sensitive_values = tuple(dict.fromkeys(
                (*self._sensitive_values(request), *adapter_context.sensitive_values)
            ))
            parser = StructuredOutputParser(self.adapter.spec.tool_id, sensitive_values)
            raw_redactor = StreamingSecretRedactor(sensitive_values)
            raw_file = self._open_private_binary(raw_path)
            display_file = self._open_private_text(display_path)
            prepared = self.adapter.prepare(request, runtime_dir)
            prepared.env.update(adapter_context.env)
            trace_writer.write("command", {"argv": prepared.command})
            yield ndjson({
                "type": "run_started",
                "task_id": request.task_id,
                "tool_id": self.adapter.spec.tool_id,
            })
            if session.cancel_requested:
                canceled = True
                exit_code = 143
                error = "task canceled"
            else:
                session.process = await asyncio.create_subprocess_exec(
                    *prepared.command,
                    cwd=str(session.cwd),
                    env=prepared.env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
                if session.cancel_requested or session.timed_out:
                    try:
                        os.killpg(session.process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                assert session.process.stdout is not None
                while True:
                    line = await session.process.stdout.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
                    trace_writer.write("raw_output", decoded, level="DEBUG")
                    classification = classify_cli_error(decoded)
                    if classification and classification[0] > classified_error_priority:
                        classified_error_priority, classified_error = classification
                    assert raw_redactor is not None
                    redacted_raw = raw_redactor.feed(decoded + "\n")
                    if redacted_raw:
                        raw_file.write(redacted_raw.encode("utf-8"))
                        raw_file.flush()
                    assert parser is not None
                    for event in parser.parse_line(decoded):
                        if event["type"] == "display_delta":
                            display_file.write(event["content"])
                            display_file.flush()
                        elif event["type"] == "usage":
                            usage = dict(event["usage"])
                            trace_writer.write("usage", usage)
                        yield ndjson({**event, "task_id": request.task_id})
                exit_code = await session.process.wait()
                canceled = session.cancel_requested
                if session.timed_out:
                    if exit_code == 0:
                        exit_code = 124
                    error = f"adapter timed out after {request.timeout_seconds} seconds"
                    trace_writer.write("diagnostic", error, level="ERROR")
                elif canceled:
                    error = "task canceled"
                elif exit_code != 0:
                    error = classified_error or f"CLI exited with {exit_code}"
                    trace_writer.write("diagnostic", error, level="ERROR")
                    if classified_error:
                        yield ndjson({
                            "type": "diagnostic",
                            "task_id": request.task_id,
                            "level": "error",
                            "message": classified_error,
                        })
                assert parser is not None
                for event in parser.finish():
                    display_file.write(event["content"])
                    display_file.flush()
                    yield ndjson({**event, "task_id": request.task_id})
        except asyncio.CancelledError:
            stream_aborted = True
            canceled = True
            if session.process and session.process.returncode is None:
                try:
                    os.killpg(session.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            raise
        except Exception as exc:
            error = f"adapter execution failed: {type(exc).__name__}"
            if trace_writer:
                with suppress(Exception):
                    trace_writer.write("diagnostic", error, level="ERROR")
            yield ndjson({
                "type": "diagnostic",
                "task_id": request.task_id,
                "level": "error",
                "message": error,
            })
            exit_code = -1
        finally:
            timeout_task.cancel()
            with suppress(asyncio.CancelledError):
                await timeout_task
            if session.process and session.process.returncode is None:
                try:
                    os.killpg(session.process.pid, signal.SIGTERM)
                    await asyncio.wait_for(session.process.wait(), timeout=5)
                except (ProcessLookupError, asyncio.TimeoutError):
                    if session.process.returncode is None:
                        try:
                            os.killpg(session.process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        with suppress(asyncio.TimeoutError):
                            await asyncio.wait_for(session.process.wait(), timeout=5)
            if raw_file:
                assert raw_redactor is not None
                trailing_raw = raw_redactor.finish()
                if trailing_raw:
                    raw_file.write(trailing_raw.encode("utf-8"))
                raw_file.close()
            if display_file:
                display_file.close()
            if trace_writer:
                with suppress(Exception):
                    trace_writer.write("run_finished", {
                        "tool_id": self.adapter.spec.tool_id,
                        "exit_code": exit_code,
                        "canceled": canceled,
                        "timed_out": session.timed_out,
                        "ok": exit_code == 0 and not canceled and not session.timed_out,
                        "error": error,
                        "usage": usage,
                        "native_session_id": parser.native_session_id if parser else request.native_session_id,
                    }, level="INFO" if exit_code == 0 and not canceled and not session.timed_out else "ERROR")
                with suppress(Exception):
                    trace_writer.close()
            await adapter_stack.aclose()
            with suppress(Exception):
                self.adapter.cleanup(request, runtime_dir)
            shutil.rmtree(runtime_dir, ignore_errors=True)
            await self._unregister(request.task_id)
        if stream_aborted:
            return
        else:
            yield ndjson({
                "type": "run_finished",
                "task_id": request.task_id,
                "tool_id": self.adapter.spec.tool_id,
                "exit_code": exit_code,
                "canceled": canceled,
                "timed_out": session.timed_out,
                "ok": exit_code == 0 and not canceled and not session.timed_out,
                "error": error,
                "usage": usage,
                "native_session_id": parser.native_session_id if parser else request.native_session_id,
            })
