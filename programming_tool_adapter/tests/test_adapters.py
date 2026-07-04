import json
from pathlib import Path

import httpx
import pytest

from programming_tool_adapter.app.adapters import get_adapter
from programming_tool_adapter.app.models import RunRequest


def request_for(
    tool_id: str,
    api_format: str,
    *,
    conversation_id: str = "",
    native_session_id: str = "",
) -> RunRequest:
    return RunRequest.model_validate({
        "task_id": f"task-{tool_id}",
        "conversation_id": conversation_id,
        "native_session_id": native_session_id,
        "cwd": "/generated_sites/project",
        "prompt": "finish the task",
        "task_mode": "develop",
        "model": {
            "format": api_format,
            "base_url": "https://provider.example/v1",
            "api_key": "top-secret-key",
            "model": "test-model",
        },
        "mcp_servers": [],
        "timeout_seconds": 120,
    })


@pytest.mark.parametrize(
    ("tool_id", "api_format", "expected_executable"),
    [
        ("codex", "responses", "codex"),
        ("claude_code", "messages", "claude"),
        ("codebuddy", "chat_completions", "codebuddy"),
        ("opencode", "responses", "opencode"),
        ("kimi_code", "responses", "kimi"),
    ],
)
def test_prepare_never_persists_provider_api_key(
    tmp_path: Path,
    tool_id: str,
    api_format: str,
    expected_executable: str,
) -> None:
    adapter = get_adapter(tool_id)
    runtime_dir = tmp_path / tool_id
    runtime_dir.mkdir()
    prepared = adapter.prepare(request_for(tool_id, api_format), runtime_dir)

    assert prepared.command[0] == expected_executable
    assert "top-secret-key" not in " ".join(prepared.command)
    assert all("top-secret-key" not in path.read_text(encoding="utf-8") for path in runtime_dir.rglob("*") if path.is_file())


def test_prepare_does_not_forward_adapter_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROGRAMMING_TOOL_ADAPTER_TOKEN", "internal-adapter-secret")
    runtime_dir = tmp_path / "codex"
    runtime_dir.mkdir()

    prepared = get_adapter("codex").prepare(request_for("codex", "responses"), runtime_dir)

    assert "PROGRAMMING_TOOL_ADAPTER_TOKEN" not in prepared.env
    assert "internal-adapter-secret" not in prepared.env.values()
    assert prepared.env["DISABLE_TELEMETRY"] == "1"


def test_codex_uses_authenticated_custom_provider(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "codex"
    runtime_dir.mkdir()

    prepared = get_adapter("codex").prepare(request_for("codex", "responses"), runtime_dir)
    config = (runtime_dir / "session-state" / "config.toml").read_text(encoding="utf-8")

    assert 'model_provider = "nextproject"' in config
    assert "[model_providers.nextproject]" in config
    assert 'base_url = "https://provider.example/v1"' in config
    assert 'env_key = "NEXTPROJECT_API_KEY"' in config
    assert 'wire_api = "responses"' in config
    assert "supports_websockets = false" in config
    assert prepared.env["NEXTPROJECT_API_KEY"] == "top-secret-key"
    assert prepared.env["GIT_AUTHOR_NAME"] == "NextProject"
    assert prepared.env["GIT_AUTHOR_EMAIL"] == "bot@nextproject"
    assert prepared.env["GIT_COMMITTER_NAME"] == "NextProject"
    assert prepared.env["GIT_COMMITTER_EMAIL"] == "bot@nextproject"
    assert "top-secret-key" not in config


@pytest.mark.parametrize(
    ("tool_id", "api_format", "resume_flag"),
    [
        ("codex", "responses", "resume"),
        ("claude_code", "messages", "--resume"),
        ("codebuddy", "chat_completions", "--resume"),
        ("opencode", "responses", "--session"),
        ("kimi_code", "responses", "--session"),
    ],
)
def test_prepare_resumes_explicit_native_session(
    tmp_path: Path,
    tool_id: str,
    api_format: str,
    resume_flag: str,
) -> None:
    runtime_dir = tmp_path / tool_id
    runtime_dir.mkdir()
    prepared = get_adapter(tool_id).prepare(
        request_for(tool_id, api_format, native_session_id="session-123"),
        runtime_dir,
    )

    assert resume_flag in prepared.command
    assert "session-123" in prepared.command
    assert "finish the task" in prepared.command


@pytest.mark.parametrize(
    ("tool_id", "api_format", "env_name"),
    [
        ("codex", "responses", "CODEX_HOME"),
        ("claude_code", "messages", "HOME"),
        ("codebuddy", "chat_completions", "CODEBUDDY_CONFIG_DIR"),
        ("opencode", "responses", "XDG_DATA_HOME"),
        ("kimi_code", "responses", "KIMI_CODE_HOME"),
    ],
)
def test_conversation_state_uses_persistent_isolated_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_id: str,
    api_format: str,
    env_name: str,
) -> None:
    session_root = tmp_path / "sessions"
    monkeypatch.setenv("PROGRAMMING_SESSION_ROOT", str(session_root))
    runtime_dir = tmp_path / "runtime" / tool_id
    runtime_dir.mkdir(parents=True)
    request = request_for(tool_id, api_format, conversation_id="conversation-123")

    prepared = get_adapter(tool_id).prepare(request, runtime_dir)

    persistent_root = session_root / tool_id / "conversation-123"
    assert persistent_root.is_dir()
    assert Path(prepared.env[env_name]).is_relative_to(persistent_root)


@pytest.mark.parametrize("tool_id", ["claude_code", "codebuddy"])
def test_streaming_tools_request_partial_messages(tmp_path: Path, tool_id: str) -> None:
    api_format = "messages" if tool_id == "claude_code" else "chat_completions"
    runtime_dir = tmp_path / tool_id
    runtime_dir.mkdir()

    prepared = get_adapter(tool_id).prepare(request_for(tool_id, api_format), runtime_dir)

    assert "--include-partial-messages" in prepared.command
    if tool_id == "claude_code":
        assert "--dangerously-skip-permissions" in prepared.command


def test_codex_rejects_non_responses_format(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "codex"
    runtime_dir.mkdir()
    with pytest.raises(ValueError, match="does not support messages"):
        get_adapter("codex").prepare(request_for("codex", "messages"), runtime_dir)


def test_claude_is_hidden_but_keeps_adapter_metadata() -> None:
    spec = get_adapter("claude_code").spec
    assert spec.visible is False
    assert spec.branch_prefix == "claude-code/"
    assert spec.version == "2.1.210"


def test_codebuddy_prepare_does_not_expose_provider_credentials_to_cli(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "codebuddy"
    runtime_dir.mkdir()

    prepared = get_adapter("codebuddy").prepare(
        request_for("codebuddy", "messages"),
        runtime_dir,
    )

    assert "NEXTPROJECT_API_KEY" not in prepared.env
    assert "OPENAI_API_KEY" not in prepared.env
    assert "ANTHROPIC_API_KEY" not in prepared.env
    assert "CODEBUDDY_API_KEY" not in prepared.env
    assert "CODEBUDDY_BASE_URL" not in prepared.env
    assert "top-secret-key" not in prepared.env.values()


def test_kimi_prepare_uses_env_model_without_exposing_provider_credentials(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "kimi"
    runtime_dir.mkdir()

    prepared = get_adapter("kimi_code").prepare(
        request_for("kimi_code", "messages", native_session_id="session-123"),
        runtime_dir,
    )

    assert prepared.command == [
        "kimi",
        "--session",
        "session-123",
        "-p",
        "finish the task",
        "--output-format",
        "stream-json",
    ]
    assert prepared.env["KIMI_DISABLE_TELEMETRY"] == "1"
    assert prepared.env["KIMI_CODE_NO_AUTO_UPDATE"] == "1"
    assert "NEXTPROJECT_API_KEY" not in prepared.env
    assert "OPENAI_API_KEY" not in prepared.env
    assert "ANTHROPIC_API_KEY" not in prepared.env
    assert "KIMI_MODEL_API_KEY" not in prepared.env
    assert "top-secret-key" not in prepared.env.values()


def test_kimi_prepare_maps_stdio_http_and_sse_mcp_servers(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "kimi-mcp"
    runtime_dir.mkdir()
    request = RunRequest.model_validate({
        "task_id": "task-kimi-mcp",
        "cwd": "/generated_sites/project",
        "prompt": "use mcp",
        "model": {
            "format": "chat_completions",
            "base_url": "https://provider.example/v1",
            "api_key": "top-secret-key",
            "model": "test-model",
        },
        "mcp_servers": [
            {
                "service_id": "stdio service",
                "config": {
                    "command": "python",
                    "args": ["-m", "example_mcp"],
                    "env": {"MCP_MODE": "test"},
                    "cwd": "/generated_sites/project",
                },
            },
            {
                "service_id": "http.service",
                "config": {
                    "transport": "http",
                    "url": "https://mcp.example.test/rpc",
                    "headers": {"X-Test": "yes"},
                },
            },
            {
                "service_id": "sse.service",
                "config": {
                    "transport": "sse",
                    "url": "https://mcp.example.test/events",
                    "bearer_token_env_var": "MCP_BEARER_TOKEN",
                },
            },
        ],
    })

    adapter = get_adapter("kimi_code")
    prepared = adapter.prepare(request, runtime_dir)
    config = json.loads((Path(prepared.env["KIMI_CODE_HOME"]) / "mcp.json").read_text(encoding="utf-8"))

    assert config["mcpServers"]["stdio-service"] == {
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "example_mcp"],
        "env": {"MCP_MODE": "test"},
        "cwd": "/generated_sites/project",
        "enabled": True,
    }
    assert config["mcpServers"]["http-service"] == {
        "transport": "http",
        "url": "https://mcp.example.test/rpc",
        "headers": {"X-Test": "yes"},
        "enabled": True,
    }
    assert config["mcpServers"]["sse-service"] == {
        "transport": "sse",
        "url": "https://mcp.example.test/events",
        "bearerTokenEnvVar": "MCP_BEARER_TOKEN",
        "enabled": True,
    }
    adapter.cleanup(request, runtime_dir)
    assert not (Path(prepared.env["KIMI_CODE_HOME"]) / "mcp.json").exists()


@pytest.mark.parametrize(
    ("api_format", "provider_package"),
    [
        ("responses", "@ai-sdk/openai"),
        ("messages", "@ai-sdk/anthropic"),
        ("chat_completions", "@ai-sdk/openai-compatible"),
    ],
)
def test_opencode_prepare_generates_provider_model_and_cli_args(
    tmp_path: Path,
    api_format: str,
    provider_package: str,
) -> None:
    runtime_dir = tmp_path / api_format
    runtime_dir.mkdir()

    prepared = get_adapter("opencode").prepare(request_for("opencode", api_format), runtime_dir)
    config = json.loads(Path(prepared.env["OPENCODE_CONFIG"]).read_text(encoding="utf-8"))
    provider = config["provider"]["nextproject"]

    assert provider["npm"] == provider_package
    assert provider["options"] == {
        "apiKey": "{env:NEXTPROJECT_API_KEY}",
        "baseURL": "https://provider.example/v1",
    }
    assert provider["models"] == {"test-model": {"name": "test-model"}}
    assert config["model"] == "nextproject/test-model"
    assert prepared.command == [
        "opencode",
        "run",
        "--format",
        "json",
        "--auto",
        "--model",
        "nextproject/test-model",
        "finish the task",
    ]


def test_opencode_prepare_maps_remote_and_local_mcp_servers(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "opencode-mcp"
    runtime_dir.mkdir()
    request = RunRequest.model_validate({
        "task_id": "task-opencode-mcp",
        "cwd": "/generated_sites/project",
        "prompt": "use mcp",
        "model": {
            "format": "responses",
            "base_url": "https://provider.example/v1",
            "api_key": "top-secret-key",
            "model": "test-model",
        },
        "mcp_servers": [
            {
                "service_id": "remote.service",
                "config": {
                    "url": "https://mcp.example.test/rpc",
                    "headers": {"Authorization": "Bearer mcp-token"},
                },
            },
            {
                "service_id": "local service",
                "config": {
                    "command": "python",
                    "args": ["-m", "example_mcp"],
                    "env": {"MCP_MODE": "test"},
                },
            },
        ],
    })

    prepared = get_adapter("opencode").prepare(request, runtime_dir)
    config = json.loads(Path(prepared.env["OPENCODE_CONFIG"]).read_text(encoding="utf-8"))

    assert config["mcp"]["remote-service"] == {
        "type": "remote",
        "url": "https://mcp.example.test/rpc",
        "headers": {"Authorization": "Bearer mcp-token"},
    }
    assert config["mcp"]["local-service"] == {
        "type": "local",
        "command": ["python", "-m", "example_mcp"],
        "environment": {"MCP_MODE": "test"},
    }


@pytest.mark.asyncio
async def test_codebuddy_run_context_uses_loopback_proxy_and_one_time_token() -> None:
    adapter = get_adapter("codebuddy")

    async with adapter.run_context(request_for("codebuddy", "responses")) as context:
        assert context.env["CODEBUDDY_BASE_URL"].startswith("http://127.0.0.1:")
        assert context.env["CODEBUDDY_API_KEY"] != "top-secret-key"
        assert "127.0.0.1" in context.env["NO_PROXY"]
        assert context.sensitive_values == (context.env["CODEBUDDY_API_KEY"],)
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f'{context.env["CODEBUDDY_BASE_URL"]}/health')
        assert response.json() == {"ok": True, "format": "responses"}


@pytest.mark.asyncio
@pytest.mark.parametrize("api_format", ["responses", "messages", "chat_completions"])
async def test_kimi_run_context_uses_loopback_proxy_and_one_time_token(api_format: str) -> None:
    adapter = get_adapter("kimi_code")

    async with adapter.run_context(request_for("kimi_code", api_format)) as context:
        assert context.env["KIMI_MODEL_PROVIDER_TYPE"] == "openai"
        assert context.env["KIMI_MODEL_NAME"] == "test-model"
        assert context.env["KIMI_MODEL_BASE_URL"].startswith("http://127.0.0.1:")
        assert context.env["KIMI_MODEL_BASE_URL"].endswith("/v1")
        assert context.env["KIMI_MODEL_API_KEY"] != "top-secret-key"
        assert "127.0.0.1" in context.env["NO_PROXY"]
        assert context.sensitive_values == (context.env["KIMI_MODEL_API_KEY"],)
        health_url = context.env["KIMI_MODEL_BASE_URL"].removesuffix("/v1") + "/health"
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(health_url)
        assert response.json() == {"ok": True, "format": api_format}
