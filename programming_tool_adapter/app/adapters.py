from __future__ import annotations

import json
import os
import re
import secrets
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from .codebuddy_proxy import ProviderProxyConfig, serve_provider_proxy
from .models import ApiFormat, McpService, RunRequest


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    name: str
    version: str
    visible: bool
    supported_formats: tuple[ApiFormat, ...]
    branch_prefix: str
    executable: str
    supports_mcp: bool = True


@dataclass
class PreparedRun:
    command: list[str]
    env: dict[str, str]


@dataclass(frozen=True)
class AdapterRunContext:
    env: dict[str, str]
    sensitive_values: tuple[str, ...] = ()


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", value).strip("-") or "service"


def _mcp_server_payload(service: McpService) -> dict[str, Any] | None:
    config = dict(service.config or {})
    if config.get("url"):
        result: dict[str, Any] = {"type": "http", "url": str(config["url"])}
        if config.get("headers"):
            result["headers"] = dict(config["headers"])
        return result
    if config.get("command"):
        return {
            "type": "stdio",
            "command": str(config["command"]),
            "args": [str(value) for value in (config.get("args") or [])],
            "env": {str(key): str(value) for key, value in (config.get("env") or {}).items()},
        }
    return None


def _kimi_mcp_server_payload(service: McpService) -> dict[str, Any] | None:
    config = dict(service.config or {})
    if config.get("url"):
        transport = str(config.get("transport") or config.get("type") or "http").strip().lower()
        result: dict[str, Any] = {
            "transport": "sse" if transport == "sse" else "http",
            "url": str(config["url"]),
            "enabled": True,
        }
        if config.get("headers"):
            result["headers"] = {str(key): str(value) for key, value in dict(config["headers"]).items()}
        bearer_token_env_var = config.get("bearerTokenEnvVar") or config.get("bearer_token_env_var")
        if bearer_token_env_var:
            result["bearerTokenEnvVar"] = str(bearer_token_env_var)
        return result
    if config.get("command"):
        result = {
            "transport": "stdio",
            "command": str(config["command"]),
            "args": [str(value) for value in (config.get("args") or [])],
            "env": {str(key): str(value) for key, value in (config.get("env") or {}).items()},
            "enabled": True,
        }
        if config.get("cwd"):
            result["cwd"] = str(config["cwd"])
        return result
    return None


def _write_private(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


class ProgrammingToolAdapter(ABC):
    spec: ToolSpec

    def validate_format(self, api_format: ApiFormat) -> None:
        if api_format not in self.spec.supported_formats:
            supported = ", ".join(self.spec.supported_formats)
            raise ValueError(f"{self.spec.tool_id} does not support {api_format}; expected one of: {supported}")

    @asynccontextmanager
    async def run_context(self, request: RunRequest) -> AsyncIterator[AdapterRunContext]:
        del request
        yield AdapterRunContext(env={})

    def session_state_dir(self, request: RunRequest, runtime_dir: Path) -> Path:
        if not request.conversation_id:
            path = runtime_dir / "session-state"
            path.mkdir(mode=0o700, exist_ok=True)
            return path
        root = Path(os.getenv("PROGRAMMING_SESSION_ROOT", "/shared/programming_sessions"))
        root.mkdir(parents=True, exist_ok=True)
        resolved_root = root.resolve(strict=True)
        path = resolved_root / self.spec.tool_id / request.conversation_id
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("conversation session state escapes PROGRAMMING_SESSION_ROOT") from exc
        if path.is_symlink() or not resolved.is_dir():
            raise ValueError("conversation session state must be a directory")
        resolved.chmod(0o700)
        return resolved

    def cleanup(self, request: RunRequest, runtime_dir: Path) -> None:
        del request, runtime_dir

    @staticmethod
    def _base_env(request: RunRequest, runtime_dir: Path) -> dict[str, str]:
        settings = request.model_settings
        api_key = settings.api_key.get_secret_value()
        passthrough_names = {
            "PATH",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TZ",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "NODE_EXTRA_CA_CERTS",
        }
        env = {
            key: value
            for key, value in os.environ.items()
            if key in passthrough_names
        }
        env.update({
            "HOME": str(runtime_dir),
            "TMPDIR": str(runtime_dir),
            "NEXTPROJECT_API_KEY": api_key,
            "NEXTPROJECT_API_FORMAT": settings.api_format,
            "GIT_AUTHOR_NAME": "NextProject",
            "GIT_AUTHOR_EMAIL": "bot@nextproject",
            "GIT_COMMITTER_NAME": "NextProject",
            "GIT_COMMITTER_EMAIL": "bot@nextproject",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "DO_NOT_TRACK": "1",
            "OTEL_SDK_DISABLED": "true",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        })
        if settings.api_format in {"responses", "chat_completions"}:
            env["OPENAI_API_KEY"] = api_key
            if settings.base_url:
                env["OPENAI_BASE_URL"] = settings.base_url.rstrip("/")
        if settings.api_format == "messages":
            env["ANTHROPIC_API_KEY"] = api_key
            if settings.base_url:
                env["ANTHROPIC_BASE_URL"] = settings.base_url.rstrip("/")
        return env

    @abstractmethod
    def prepare(self, request: RunRequest, runtime_dir: Path) -> PreparedRun:
        raise NotImplementedError


class CodexAdapter(ProgrammingToolAdapter):
    spec = ToolSpec(
        tool_id="codex",
        name="Codex",
        version="0.144.4",
        visible=True,
        supported_formats=("responses",),
        branch_prefix="codex/",
        executable="codex",
    )

    def prepare(self, request: RunRequest, runtime_dir: Path) -> PreparedRun:
        self.validate_format(request.model_settings.api_format)
        codex_home = self.session_state_dir(request, runtime_dir)
        provider_base_url = request.model_settings.base_url.rstrip("/") or "https://api.openai.com/v1"
        lines = [
            'cli_auth_credentials_store = "file"',
            'model_provider = "nextproject"',
            "",
            "[model_providers.nextproject]",
            'name = "NextProject project Provider"',
            f"base_url = {json.dumps(provider_base_url)}",
            'env_key = "NEXTPROJECT_API_KEY"',
            'wire_api = "responses"',
            "supports_websockets = false",
        ]
        for service in request.mcp_services:
            config = dict(service.config or {})
            service_id = _safe_id(service.service_id)
            if config.get("url"):
                lines.extend([
                    "",
                    f'[mcp_servers."{service_id}"]',
                    f'url = {json.dumps(str(config["url"]))}',
                    "enabled = true",
                ])
                if config.get("bearer_token_env_var"):
                    lines.append(f'bearer_token_env_var = {json.dumps(str(config["bearer_token_env_var"]))}')
            elif config.get("command"):
                args = [str(value) for value in (config.get("args") or [])]
                lines.extend([
                    "",
                    f'[mcp_servers."{service_id}"]',
                    f'command = {json.dumps(str(config["command"]))}',
                    f"args = {json.dumps(args, ensure_ascii=False)}",
                    "enabled = true",
                ])
                service_env = dict(config.get("env") or {})
                if service_env:
                    lines.append(f'[mcp_servers."{service_id}".env]')
                    for key, value in service_env.items():
                        lines.append(f'{json.dumps(str(key))} = {json.dumps(str(value))}')
        config_path = _write_private(runtime_dir / "codex-config.toml", "\n".join(lines) + "\n")
        config_link = codex_home / "config.toml"
        if config_link.exists() or config_link.is_symlink():
            config_link.unlink()
        config_link.symlink_to(config_path)

        command = ["codex", "exec"]
        if request.native_session_id:
            command.append("resume")
        command.extend([
            "--json",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
        ])
        if request.model_settings.model:
            command.extend(["--model", request.model_settings.model])
        if request.native_session_id:
            command.append(request.native_session_id)
        command.append(request.prompt)
        env = self._base_env(request, runtime_dir)
        for service in request.mcp_services:
            config = dict(service.config or {})
            env_name = str(config.get("bearer_token_env_var") or "").strip()
            authorization = str((config.get("headers") or {}).get("Authorization") or "")
            if env_name and authorization.lower().startswith("bearer "):
                env[env_name] = authorization[7:].strip()
        env["CODEX_HOME"] = str(codex_home)
        env["CODEX_SQLITE_HOME"] = str(codex_home)
        return PreparedRun(command=command, env=env)

    def cleanup(self, request: RunRequest, runtime_dir: Path) -> None:
        config_link = self.session_state_dir(request, runtime_dir) / "config.toml"
        if config_link.is_symlink():
            config_link.unlink()


class ClaudeCodeAdapter(ProgrammingToolAdapter):
    spec = ToolSpec(
        tool_id="claude_code",
        name="Claude Code",
        version="2.1.210",
        visible=False,
        supported_formats=("messages",),
        branch_prefix="claude-code/",
        executable="claude",
    )

    def prepare(self, request: RunRequest, runtime_dir: Path) -> PreparedRun:
        self.validate_format(request.model_settings.api_format)
        mcp_servers = {}
        for service in request.mcp_services:
            payload = _mcp_server_payload(service)
            if payload:
                mcp_servers[_safe_id(service.service_id)] = payload
        mcp_path = _write_private(
            runtime_dir / "claude-mcp.json",
            json.dumps({"mcpServers": mcp_servers}, ensure_ascii=False),
        )
        command = [
            "claude",
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--mcp-config",
            str(mcp_path),
            "--strict-mcp-config",
        ]
        if request.model_settings.model:
            command.extend(["--model", request.model_settings.model])
        if request.native_session_id:
            command.extend(["--resume", request.native_session_id])
        command.extend(["-p", request.prompt])
        env = self._base_env(request, runtime_dir)
        session_home = self.session_state_dir(request, runtime_dir)
        env["HOME"] = str(session_home)
        env["CLAUDE_HOME"] = str(session_home / ".claude")
        env["CLAUDE_CONFIG_DIR"] = str(session_home / ".claude")
        return PreparedRun(command=command, env=env)


class CodeBuddyAdapter(ProgrammingToolAdapter):
    spec = ToolSpec(
        tool_id="codebuddy",
        name="CodeBuddy",
        version="2.121.2",
        visible=True,
        supported_formats=("responses", "messages", "chat_completions"),
        branch_prefix="codebuddy/",
        executable="codebuddy",
    )

    @asynccontextmanager
    async def run_context(self, request: RunRequest) -> AsyncIterator[AdapterRunContext]:
        settings = request.model_settings
        proxy_token = secrets.token_urlsafe(32)
        config = ProviderProxyConfig(
            api_format=settings.api_format,
            base_url=settings.base_url,
            api_key=settings.api_key.get_secret_value(),
            model=settings.model,
            inbound_token=proxy_token,
            timeout_seconds=float(request.timeout_seconds),
        )
        async with serve_provider_proxy(config) as proxy:
            no_proxy = ",".join(filter(None, (
                os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "",
                "127.0.0.1",
                "localhost",
            )))
            yield AdapterRunContext(
                env={
                    "CODEBUDDY_API_KEY": proxy_token,
                    "CODEBUDDY_BASE_URL": proxy.base_url,
                    "NO_PROXY": no_proxy,
                    "no_proxy": no_proxy,
                },
                sensitive_values=(proxy_token,),
            )

    def prepare(self, request: RunRequest, runtime_dir: Path) -> PreparedRun:
        self.validate_format(request.model_settings.api_format)
        mcp_servers = {}
        for service in request.mcp_services:
            payload = _mcp_server_payload(service)
            if payload:
                mcp_servers[_safe_id(service.service_id)] = payload
        mcp_path = _write_private(
            runtime_dir / "codebuddy-mcp.json",
            json.dumps({"mcpServers": mcp_servers}, ensure_ascii=False),
        )
        command = [
            "codebuddy",
            "-p",
            "-y",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--mcp-config",
            str(mcp_path),
            "--strict-mcp-config",
        ]
        if request.model_settings.model:
            command.extend(["--model", request.model_settings.model])
        if request.native_session_id:
            command.extend(["--resume", request.native_session_id])
        command.append(request.prompt)
        env = self._base_env(request, runtime_dir)
        for name in (
            "NEXTPROJECT_API_KEY",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
        ):
            env.pop(name, None)
        session_home = self.session_state_dir(request, runtime_dir)
        env["HOME"] = str(session_home)
        env["CODEBUDDY_CONFIG_DIR"] = str(session_home / ".codebuddy")
        return PreparedRun(command=command, env=env)


class KimiCodeAdapter(ProgrammingToolAdapter):
    spec = ToolSpec(
        tool_id="kimi_code",
        name="Kimi Code",
        version="0.27.0",
        visible=True,
        supported_formats=("responses", "messages", "chat_completions"),
        branch_prefix="kimi-code/",
        executable="kimi",
    )

    @asynccontextmanager
    async def run_context(self, request: RunRequest) -> AsyncIterator[AdapterRunContext]:
        settings = request.model_settings
        proxy_token = secrets.token_urlsafe(32)
        config = ProviderProxyConfig(
            api_format=settings.api_format,
            base_url=settings.base_url,
            api_key=settings.api_key.get_secret_value(),
            model=settings.model,
            inbound_token=proxy_token,
            timeout_seconds=float(request.timeout_seconds),
        )
        async with serve_provider_proxy(config) as proxy:
            no_proxy = ",".join(filter(None, (
                os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "",
                "127.0.0.1",
                "localhost",
            )))
            yield AdapterRunContext(
                env={
                    "KIMI_MODEL_PROVIDER_TYPE": "openai",
                    "KIMI_MODEL_NAME": settings.model,
                    "KIMI_MODEL_BASE_URL": f"{proxy.base_url}/v1",
                    "KIMI_MODEL_API_KEY": proxy_token,
                    "NO_PROXY": no_proxy,
                    "no_proxy": no_proxy,
                },
                sensitive_values=(proxy_token,),
            )

    def prepare(self, request: RunRequest, runtime_dir: Path) -> PreparedRun:
        self.validate_format(request.model_settings.api_format)
        kimi_home = self.session_state_dir(request, runtime_dir)
        mcp_servers: dict[str, Any] = {}
        for service in request.mcp_services:
            payload = _kimi_mcp_server_payload(service)
            if payload:
                mcp_servers[_safe_id(service.service_id)] = payload
        mcp_path = _write_private(
            runtime_dir / "kimi-mcp.json",
            json.dumps({"mcpServers": mcp_servers}, ensure_ascii=False),
        )
        mcp_link = kimi_home / "mcp.json"
        if mcp_link.exists() or mcp_link.is_symlink():
            mcp_link.unlink()
        mcp_link.symlink_to(mcp_path)

        command = ["kimi"]
        if request.native_session_id:
            command.extend(["--session", request.native_session_id])
        command.extend([
            "-p",
            request.prompt,
            "--output-format",
            "stream-json",
        ])
        env = self._base_env(request, runtime_dir)
        for name in (
            "NEXTPROJECT_API_KEY",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
        ):
            env.pop(name, None)
        env.update({
            "HOME": str(kimi_home),
            "KIMI_CODE_HOME": str(kimi_home),
            "KIMI_DISABLE_TELEMETRY": "1",
            "KIMI_CODE_NO_AUTO_UPDATE": "1",
        })
        return PreparedRun(command=command, env=env)

    def cleanup(self, request: RunRequest, runtime_dir: Path) -> None:
        mcp_link = self.session_state_dir(request, runtime_dir) / "mcp.json"
        if mcp_link.is_symlink():
            mcp_link.unlink()


class OpenCodeAdapter(ProgrammingToolAdapter):
    spec = ToolSpec(
        tool_id="opencode",
        name="OpenCode",
        version="1.18.1",
        visible=True,
        supported_formats=("responses", "messages", "chat_completions"),
        branch_prefix="opencode/",
        executable="opencode",
    )

    @staticmethod
    def _provider_package(api_format: ApiFormat) -> str:
        if api_format == "messages":
            return "@ai-sdk/anthropic"
        if api_format == "responses":
            return "@ai-sdk/openai"
        return "@ai-sdk/openai-compatible"

    def prepare(self, request: RunRequest, runtime_dir: Path) -> PreparedRun:
        self.validate_format(request.model_settings.api_format)
        settings = request.model_settings
        provider: dict[str, Any] = {
            "npm": self._provider_package(settings.api_format),
            "name": settings.provider_name or "NextProject",
            "options": {"apiKey": "{env:NEXTPROJECT_API_KEY}"},
            "models": {},
        }
        if settings.base_url:
            provider["options"]["baseURL"] = settings.base_url.rstrip("/")
        if settings.model:
            provider["models"][settings.model] = {"name": settings.model}

        mcp: dict[str, Any] = {}
        for service in request.mcp_services:
            payload = _mcp_server_payload(service)
            if not payload:
                continue
            service_id = _safe_id(service.service_id)
            if payload["type"] == "http":
                mcp[service_id] = {
                    "type": "remote",
                    "url": payload["url"],
                    **({"headers": payload["headers"]} if payload.get("headers") else {}),
                }
            else:
                mcp[service_id] = {
                    "type": "local",
                    "command": [payload["command"], *payload.get("args", [])],
                    **({"environment": payload["env"]} if payload.get("env") else {}),
                }

        config: dict[str, Any] = {
            "$schema": "https://opencode.ai/config.json",
            "provider": {"nextproject": provider},
            "mcp": mcp,
        }
        if settings.model:
            config["model"] = f"nextproject/{settings.model}"
        config_path = _write_private(
            runtime_dir / "opencode.json",
            json.dumps(config, ensure_ascii=False),
        )
        command = ["opencode", "run", "--format", "json", "--auto"]
        if request.native_session_id:
            command.extend(["--session", request.native_session_id])
        if settings.model:
            command.extend(["--model", f"nextproject/{settings.model}"])
        command.append(request.prompt)
        env = self._base_env(request, runtime_dir)
        session_home = self.session_state_dir(request, runtime_dir)
        env["HOME"] = str(session_home)
        env["XDG_DATA_HOME"] = str(session_home / ".local" / "share")
        env["XDG_STATE_HOME"] = str(session_home / ".local" / "state")
        env["XDG_CACHE_HOME"] = str(runtime_dir / "opencode-cache")
        env["XDG_CONFIG_HOME"] = str(runtime_dir / "opencode-config")
        env["OPENCODE_CONFIG"] = str(config_path)
        return PreparedRun(command=command, env=env)


ADAPTERS: dict[str, ProgrammingToolAdapter] = {
    adapter.spec.tool_id: adapter
    for adapter in (CodexAdapter(), ClaudeCodeAdapter(), CodeBuddyAdapter(), OpenCodeAdapter(), KimiCodeAdapter())
}


def get_adapter(tool_id: str) -> ProgrammingToolAdapter:
    try:
        return ADAPTERS[tool_id]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported TOOL_ID: {tool_id}") from exc
