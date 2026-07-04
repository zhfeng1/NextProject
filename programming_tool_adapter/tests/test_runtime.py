import asyncio
import json
import stat
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import pytest

from programming_tool_adapter.app.adapters import (
    AdapterRunContext,
    PreparedRun,
    ProgrammingToolAdapter,
    ToolSpec,
)
from programming_tool_adapter.app.models import McpService, RunRequest
from programming_tool_adapter.app.runtime import RunManager, RunSession, classify_cli_error


class DummyCodexAdapter(ProgrammingToolAdapter):
    spec = ToolSpec(
        tool_id="codex",
        name="Codex",
        version="test",
        visible=True,
        supported_formats=("responses",),
        branch_prefix="codex/",
        executable=sys.executable,
    )

    def prepare(self, request: RunRequest, runtime_dir: Path) -> PreparedRun:
        script = (
            "import json, os; "
            "print(json.dumps({'type':'item.completed','item':"
            "{'type':'agent_message','text':'key=' + os.environ['NEXTPROJECT_API_KEY']}})); "
            "print(json.dumps({'type':'turn.completed','usage':"
            "{'input_tokens':12,'output_tokens':4}}))"
        )
        return PreparedRun(
            command=[sys.executable, "-c", script],
            env=self._base_env(request, runtime_dir),
        )


class ContextCodexAdapter(DummyCodexAdapter):
    context_exited = False

    @asynccontextmanager
    async def run_context(self, request: RunRequest) -> AsyncIterator[AdapterRunContext]:
        del request
        try:
            yield AdapterRunContext(
                env={"SHORT_LIVED_TOKEN": "proxy-local-secret"},
                sensitive_values=("proxy-local-secret",),
            )
        finally:
            self.context_exited = True

    def prepare(self, request: RunRequest, runtime_dir: Path) -> PreparedRun:
        script = (
            "import json, os; "
            "print(json.dumps({'type':'item.completed','item':"
            "{'type':'agent_message','text':'token=' + os.environ['SHORT_LIVED_TOKEN']}}))"
        )
        return PreparedRun(
            command=[sys.executable, "-c", script],
            env=self._base_env(request, runtime_dir),
        )


class FailingCodexAdapter(DummyCodexAdapter):
    def prepare(self, request: RunRequest, runtime_dir: Path) -> PreparedRun:
        script = (
            "import json, sys; "
            "print(json.dumps({'type':'turn.failed','error':"
            "{'message':'unexpected status 401 Unauthorized: Invalid token'}})); "
            "sys.exit(1)"
        )
        return PreparedRun(
            command=[sys.executable, "-c", script],
            env=self._base_env(request, runtime_dir),
        )


class SessionCodexAdapter(DummyCodexAdapter):
    def prepare(self, request: RunRequest, runtime_dir: Path) -> PreparedRun:
        script = (
            "import json; "
            "print(json.dumps({'type':'thread.started','thread_id':'native-session-123'})); "
            "print(json.dumps({'type':'item.completed','item':"
            "{'type':'agent_message','text':'done'}}))"
        )
        return PreparedRun(
            command=[sys.executable, "-c", script],
            env=self._base_env(request, runtime_dir),
        )


def run_request(cwd: Path) -> RunRequest:
    return RunRequest.model_validate({
        "task_id": "task-runtime",
        "cwd": str(cwd),
        "prompt": "finish",
        "model": {
            "format": "responses",
            "api_key": "top-secret-key",
            "base_url": "https://provider.example/v1",
            "model": "test-model",
        },
    })


@pytest.mark.asyncio
async def test_stream_redacts_secrets_from_events_and_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "generated_sites"
    cwd = workspace / "project"
    cwd.mkdir(parents=True)
    manager = RunManager(DummyCodexAdapter())
    manager.workspace_root = workspace.resolve()
    manager.artifacts_root = tmp_path / "artifacts"
    manager.runtime_root = tmp_path / "runtime"
    session = await manager.reserve(run_request(cwd))

    events = [json.loads(chunk) async for chunk in manager.stream(session)]

    display = "".join(event.get("content", "") for event in events if event["type"] == "display_delta")
    assert display == "key=[REDACTED]"
    assert events[-1]["type"] == "run_finished"
    assert events[-1]["ok"] is True
    raw = (manager.artifacts_root / "task-runtime" / "codex-raw-output.log").read_text(encoding="utf-8")
    user_output = (manager.artifacts_root / "task-runtime" / "codex-user-output.log").read_text(encoding="utf-8")
    trace_path = manager.artifacts_root / "task-runtime" / "codex-execution-trace.ndjson"
    trace_text = trace_path.read_text(encoding="utf-8")
    trace_events = [json.loads(line) for line in trace_text.splitlines()]
    assert "top-secret-key" not in raw
    assert "top-secret-key" not in user_output
    assert "top-secret-key" not in trace_text
    assert "[REDACTED]" in raw
    assert [event["seq"] for event in trace_events] == list(range(1, len(trace_events) + 1))
    assert [event["kind"] for event in trace_events] == [
        "run_context",
        "command",
        "raw_output",
        "raw_output",
        "usage",
        "run_finished",
    ]
    assert trace_events[0]["content"] == {
        "prompt": "finish",
        "cwd": str(cwd.resolve()),
        "conversation_id": "",
        "native_session_id": "",
        "model": {
            "format": "responses",
            "base_url": "https://provider.example/v1",
            "model": "test-model",
            "provider_name": "",
        },
        "mcp_servers": [],
        "task_mode": "develop",
    }
    assert trace_events[1]["content"]["argv"][0] == sys.executable
    assert "[REDACTED]" in trace_events[2]["content"]
    assert trace_events[4]["content"] == {"input_tokens": 12, "output_tokens": 4}
    assert trace_events[-1]["content"]["ok"] is True
    assert trace_events[-1]["content"]["usage"] == {"input_tokens": 12, "output_tokens": 4}
    assert stat.S_IMODE(trace_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(trace_path.parent.stat().st_mode) == 0o700


@pytest.mark.asyncio
async def test_run_finished_returns_native_session_id(tmp_path: Path) -> None:
    workspace = tmp_path / "generated_sites"
    cwd = workspace / "project"
    cwd.mkdir(parents=True)
    manager = RunManager(SessionCodexAdapter())
    manager.workspace_root = workspace.resolve()
    manager.artifacts_root = tmp_path / "artifacts"
    manager.runtime_root = tmp_path / "runtime"

    session = await manager.reserve(run_request(cwd))
    events = [json.loads(chunk) async for chunk in manager.stream(session)]

    assert events[-1]["type"] == "run_finished"
    assert events[-1]["native_session_id"] == "native-session-123"


@pytest.mark.asyncio
async def test_stream_applies_and_redacts_short_lived_adapter_context(tmp_path: Path) -> None:
    workspace = tmp_path / "generated_sites"
    cwd = workspace / "project"
    cwd.mkdir(parents=True)
    adapter = ContextCodexAdapter()
    manager = RunManager(adapter)
    manager.workspace_root = workspace.resolve()
    manager.artifacts_root = tmp_path / "artifacts"
    manager.runtime_root = tmp_path / "runtime"
    session = await manager.reserve(run_request(cwd))

    events = [json.loads(chunk) async for chunk in manager.stream(session)]

    display = "".join(event.get("content", "") for event in events if event["type"] == "display_delta")
    assert display == "token=[REDACTED]"
    assert events[-1]["ok"] is True
    assert adapter.context_exited is True
    raw = (manager.artifacts_root / "task-runtime" / "codex-raw-output.log").read_text(encoding="utf-8")
    assert "proxy-local-secret" not in raw
    trace = (manager.artifacts_root / "task-runtime" / "codex-execution-trace.ndjson").read_text(encoding="utf-8")
    assert "proxy-local-secret" not in trace


@pytest.mark.asyncio
async def test_trace_records_redacted_mcp_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "generated_sites"
    cwd = workspace / "project"
    cwd.mkdir(parents=True)
    manager = RunManager(DummyCodexAdapter())
    manager.workspace_root = workspace.resolve()
    manager.artifacts_root = tmp_path / "artifacts"
    manager.runtime_root = tmp_path / "runtime"
    request = run_request(cwd)
    request.mcp_services.append(McpService.model_validate({
        "service_id": "private-mcp",
        "name": "Private MCP",
        "description": "Internal tools",
        "config": {
            "url": "https://alice:password@mcp.example/v1?token=query-secret&safe=yes",
            "headers": {"Authorization": "Bearer mcp-bearer-secret"},
            "env": {"MCP_PASSWORD": "mcp-password-secret"},
        },
    }))
    session = await manager.reserve(request)

    _ = [chunk async for chunk in manager.stream(session)]

    trace_path = manager.artifacts_root / "task-runtime" / "codex-execution-trace.ndjson"
    trace_text = trace_path.read_text(encoding="utf-8")
    context = json.loads(trace_text.splitlines()[0])["content"]
    assert context["mcp_servers"][0]["service_id"] == "private-mcp"
    assert context["mcp_servers"][0]["name"] == "Private MCP"
    assert context["mcp_servers"][0]["config"]["headers"]["Authorization"] == "[REDACTED]"
    assert context["mcp_servers"][0]["config"]["env"]["MCP_PASSWORD"] == "[REDACTED]"
    assert "alice" not in trace_text
    assert "query-secret" not in trace_text
    assert "mcp-bearer-secret" not in trace_text
    assert "mcp-password-secret" not in trace_text


@pytest.mark.asyncio
async def test_stream_returns_safe_classified_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "generated_sites"
    cwd = workspace / "project"
    cwd.mkdir(parents=True)
    manager = RunManager(FailingCodexAdapter())
    manager.workspace_root = workspace.resolve()
    manager.artifacts_root = tmp_path / "artifacts"
    manager.runtime_root = tmp_path / "runtime"
    session = await manager.reserve(run_request(cwd))

    events = [json.loads(chunk) async for chunk in manager.stream(session)]

    diagnostics = [event["message"] for event in events if event["type"] == "diagnostic"]
    assert diagnostics == ["Provider 认证失败，请检查项目模型配置中的 API Key"]
    assert events[-1]["type"] == "run_finished"
    assert events[-1]["exit_code"] == 1
    assert events[-1]["error"] == diagnostics[0]
    assert "Invalid token" not in json.dumps(events, ensure_ascii=False)
    trace_path = manager.artifacts_root / "task-runtime" / "codex-execution-trace.ndjson"
    trace_events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert trace_events[-2] == {
        "seq": trace_events[-2]["seq"],
        "ts": trace_events[-2]["ts"],
        "kind": "diagnostic",
        "level": "ERROR",
        "content": diagnostics[0],
    }
    assert trace_events[-1]["kind"] == "run_finished"
    assert trace_events[-1]["level"] == "ERROR"
    assert trace_events[-1]["content"]["ok"] is False
    assert trace_events[-1]["content"]["exit_code"] == 1
    assert trace_events[-1]["content"]["error"] == diagnostics[0]


def test_artifact_directory_rejects_symlink_escape(tmp_path: Path) -> None:
    manager = RunManager(DummyCodexAdapter())
    manager.artifacts_root = tmp_path / "artifacts"
    manager.artifacts_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (manager.artifacts_root / "task-runtime").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="escapes"):
        manager._artifact_dir("task-runtime")


def test_artifact_directory_tightens_existing_permissions(tmp_path: Path) -> None:
    manager = RunManager(DummyCodexAdapter())
    manager.artifacts_root = tmp_path / "artifacts"
    task_dir = manager.artifacts_root / "task-runtime"
    task_dir.mkdir(parents=True, mode=0o755)
    task_dir.chmod(0o755)

    resolved = manager._artifact_dir("task-runtime")

    assert resolved == task_dir.resolve()
    assert stat.S_IMODE(task_dir.stat().st_mode) == 0o700


@pytest.mark.asyncio
async def test_cancel_does_not_relabel_finished_process(tmp_path: Path) -> None:
    manager = RunManager(DummyCodexAdapter())
    request = run_request(tmp_path)

    class FinishedProcess:
        returncode = 0

    manager.sessions[request.task_id] = RunSession(
        request=request,
        cwd=tmp_path,
        process=FinishedProcess(),  # type: ignore[arg-type]
    )

    result = await manager.cancel(request.task_id)

    assert result["canceled"] is False
    assert manager.sessions[request.task_id].cancel_requested is False


def test_private_output_open_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "output.log"
    link.symlink_to(target)

    with pytest.raises(OSError):
        RunManager._open_private_binary(link)
    assert target.read_text(encoding="utf-8") == "preserve"


@pytest.mark.asyncio
async def test_stream_closes_cli_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "generated_sites"
    cwd = workspace / "project"
    cwd.mkdir(parents=True)
    manager = RunManager(DummyCodexAdapter())
    manager.workspace_root = workspace.resolve()
    manager.artifacts_root = tmp_path / "artifacts"
    manager.runtime_root = tmp_path / "runtime"
    session = await manager.reserve(run_request(cwd))
    captured: dict[str, object] = {}

    class EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class FinishedProcess:
        pid = 999999
        returncode = 0
        stdout = EmptyStdout()

        async def wait(self) -> int:
            return 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        del args
        captured.update(kwargs)
        return FinishedProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    events = [json.loads(chunk) async for chunk in manager.stream(session)]

    assert events[-1]["ok"] is True
    assert captured["stdin"] is asyncio.subprocess.DEVNULL


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            '{"type":"turn.failed","error":{"message":"unexpected status 401 Unauthorized: Invalid token"}}',
            "Provider 认证失败，请检查项目模型配置中的 API Key",
        ),
        (
            '{"type":"error","message":"404 Not Found: Invalid URL (POST /v1/responses)"}',
            "Provider 接口不可用，请检查 Base URL 与启用的接口类型",
        ),
        (
            '{"type":"error","message":"unsupported model: missing-model"}',
            "Provider 不支持所选模型，请检查项目模型配置中的模型名称",
        ),
    ],
)
def test_classify_cli_error_returns_safe_diagnostic(line: str, expected: str) -> None:
    result = classify_cli_error(line)
    assert result is not None
    assert result[1] == expected


@pytest.mark.parametrize("open_output", [RunManager._open_private_binary, RunManager._open_private_text])
def test_private_output_open_tightens_existing_file_permissions(tmp_path: Path, open_output) -> None:
    output = tmp_path / "provider-output.log"
    output.write_text("existing", encoding="utf-8")
    output.chmod(0o644)

    with open_output(output):
        pass

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
