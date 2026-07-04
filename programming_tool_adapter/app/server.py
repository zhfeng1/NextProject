from __future__ import annotations

import hmac
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import StreamingResponse

from .adapters import get_adapter
from .bridge import CompatibilityBridge
from .models import RunRequest, ToolMetadata
from .runtime import RunManager


TOOL_ID = os.getenv("TOOL_ID", "codex").strip().lower()
adapter = get_adapter(TOOL_ID)
manager = RunManager(adapter)
bridge = CompatibilityBridge(TOOL_ID)


def configured_adapter_token() -> str:
    return os.getenv("PROGRAMMING_TOOL_ADAPTER_TOKEN", "") or os.getenv("ADAPTER_TOKEN", "")


def require_adapter_token(x_adapter_token: str | None = Header(default=None)) -> None:
    expected = configured_adapter_token()
    if not expected:
        raise HTTPException(status_code=503, detail="adapter token is not configured")
    if not x_adapter_token or not hmac.compare_digest(x_adapter_token, expected):
        raise HTTPException(status_code=401, detail="invalid adapter token")


def cli_version() -> str:
    if not shutil.which(adapter.spec.executable):
        return ""
    try:
        result = subprocess.run(
            [adapter.spec.executable, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or result.stderr).strip().splitlines()[0][:200]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    bridge.start()
    try:
        yield
    finally:
        bridge.stop()


app = FastAPI(title=f"{adapter.spec.name} Programming Tool Adapter", lifespan=lifespan)


@app.get("/health")
def health(response: Response) -> dict[str, Any]:
    available = bool(shutil.which(adapter.spec.executable))
    token_configured = bool(configured_adapter_token())
    ok = available and token_configured
    if not ok:
        response.status_code = 503
    return {
        "ok": ok,
        "tool_id": adapter.spec.tool_id,
        "cli_available": available,
        "version": cli_version(),
        "adapter_token_configured": token_configured,
        **({"mcp_running": bridge.mcp_status()["running"], "authenticated": bridge.authenticated()}
           if TOOL_ID in {"codex", "claude_code"} else {}),
    }


@app.get("/v1/metadata", response_model=ToolMetadata, dependencies=[Depends(require_adapter_token)])
def metadata() -> ToolMetadata:
    spec = adapter.spec
    return ToolMetadata(
        tool_id=spec.tool_id,
        name=spec.name,
        version=cli_version() or spec.version,
        visible=spec.visible,
        supported_formats=list(spec.supported_formats),
        branch_prefix=spec.branch_prefix,
        supports_mcp=spec.supports_mcp,
        cli_available=bool(shutil.which(spec.executable)),
    )


@app.post("/v1/runs", dependencies=[Depends(require_adapter_token)])
async def run(request: RunRequest) -> StreamingResponse:
    try:
        session = await manager.reserve(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(manager.stream(session), media_type="application/x-ndjson")


@app.post("/v1/runs/{task_id}/cancel", dependencies=[Depends(require_adapter_token)])
async def cancel_run(task_id: str) -> dict[str, Any]:
    return await manager.cancel(task_id)


def require_tool(expected: str) -> None:
    if TOOL_ID != expected:
        raise HTTPException(status_code=404, detail="endpoint is not available for this tool")


@app.get("/oauth/status", dependencies=[Depends(require_adapter_token)])
def oauth_status() -> dict[str, Any]:
    require_tool("codex")
    return bridge.auth_status()


@app.post("/oauth/start", dependencies=[Depends(require_adapter_token)])
def oauth_start() -> dict[str, Any]:
    require_tool("codex")
    return bridge.start_auth()


@app.get("/oauth/logs", dependencies=[Depends(require_adapter_token)])
def oauth_logs() -> dict[str, Any]:
    require_tool("codex")
    return {"ok": True, "logs": list(bridge.logs)}


@app.post("/oauth/cancel", dependencies=[Depends(require_adapter_token)])
def oauth_cancel() -> dict[str, Any]:
    require_tool("codex")
    return bridge.cancel_auth()


@app.get("/auth/status", dependencies=[Depends(require_adapter_token)])
def auth_status() -> dict[str, Any]:
    require_tool("claude_code")
    return bridge.auth_status()


@app.post("/auth/start", dependencies=[Depends(require_adapter_token)])
def auth_start() -> dict[str, Any]:
    require_tool("claude_code")
    return bridge.start_auth()


@app.get("/auth/logs", dependencies=[Depends(require_adapter_token)])
def auth_logs() -> dict[str, Any]:
    require_tool("claude_code")
    return {"ok": True, "logs": list(bridge.logs)}


@app.post("/auth/cancel", dependencies=[Depends(require_adapter_token)])
def auth_cancel() -> dict[str, Any]:
    require_tool("claude_code")
    return bridge.cancel_auth()


@app.get("/mcp/status", dependencies=[Depends(require_adapter_token)])
def mcp_status() -> dict[str, Any]:
    return bridge.mcp_status()


if __name__ == "__main__":
    import uvicorn

    default_ports = {
        "codex": 8090,
        "claude_code": 8091,
        "codebuddy": 8092,
        "opencode": 8093,
        "kimi_code": 8094,
    }
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", str(default_ports[TOOL_ID]))))
