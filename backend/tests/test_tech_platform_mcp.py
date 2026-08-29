from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select


async def _create_project_and_task(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    *,
    status: str = "running",
) -> tuple[str, str, str]:
    response = await client.post(
        "/api/v2/projects",
        json={"name": f"MCP Project {uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    project = response.json()["project"]
    project_id = project["id"]
    site_public_id = project["repos"][0]["site_id"]

    from backend.core.database import AsyncSessionLocal
    from backend.core.security import create_programming_mcp_token, decode_token
    from backend.models import Site, Task, TaskRepository

    access_token = auth_headers["Authorization"].split(" ", 1)[1]
    user_id = str(decode_token(access_token)["sub"])
    task_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        site = (
            await db.execute(select(Site).where(Site.site_id == site_public_id))
        ).scalar_one()
        task = Task(
            id=task_id,
            site_id=site.id,
            project_id=project_id,
            title="MCP test task",
            provider="codex",
            task_type="develop_code",
            status=status,
            payload_json={},
        )
        db.add(task)
        db.add(
            TaskRepository(
                task_id=task_id,
                site_id=site.id,
                repo_path=site.root_path or "",
            )
        )
        await db.commit()
        site_db_id = str(site.id)

    token = create_programming_mcp_token(
        {
            "sub": user_id,
            "task_id": task_id,
            "project_id": project_id,
            "site_ids": [site_db_id],
        }
    )
    return project_id, task_id, token


def _mcp_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
    }


def _rpc(method: str, *, request_id: int = 1, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def test_programming_task_mcp_config_uses_scoped_short_lived_token() -> None:
    from backend.core.security import decode_token
    from backend.services.task_service import task_service

    task = SimpleNamespace(id="programming-task", provider="codex")
    service = task_service._tech_platform_mcp_service(
        task=task,
        user_id="user-one",
        project_id="project-one",
        site_ids=["site-one"],
    )

    config = service["config"]
    authorization = config["headers"]["Authorization"]
    token = authorization.split(" ", 1)[1]
    claims = decode_token(token)
    assert service["service_id"] == "nextproject-tech-platform"
    assert config["url"].endswith("/mcp/tech-platform")
    assert config["bearer_token_env_var"] == "NEXTPROJECT_TECH_PLATFORM_MCP_TOKEN"
    assert claims["type"] == "programming_mcp"
    assert claims["sub"] == "user-one"
    assert claims["task_id"] == "programming-task"
    assert claims["project_id"] == "project-one"
    assert claims["site_ids"] == ["site-one"]
    assert claims["exp"] - claims["iat"] == 3600

    non_codex = task_service._tech_platform_mcp_service(
        task=SimpleNamespace(id="programming-task", provider="opencode"),
        user_id="user-one",
        project_id="project-one",
        site_ids=["site-one"],
    )
    assert "bearer_token_env_var" not in non_codex["config"]


@pytest.mark.asyncio
async def test_mcp_rejects_missing_access_and_inactive_task_tokens(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    initialize = _rpc(
        "initialize",
        params={"protocolVersion": "2025-06-18", "capabilities": {}},
    )

    response = await client.post("/mcp/tech-platform", json=initialize)
    assert response.status_code == 401

    response = await client.post(
        "/mcp/tech-platform",
        json=initialize,
        headers=auth_headers,
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid MCP token type"

    _, _, queued_token = await _create_project_and_task(
        client, auth_headers, status="queued"
    )
    response = await client.post(
        "/mcp/tech-platform",
        json=initialize,
        headers=_mcp_headers(queued_token),
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "MCP task context is no longer active"


@pytest.mark.asyncio
async def test_mcp_initialize_and_tools_list(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    _, _, token = await _create_project_and_task(client, auth_headers)

    response = await client.post(
        "/mcp/tech-platform",
        json=_rpc(
            "initialize",
            params={"protocolVersion": "2025-06-18", "capabilities": {}},
        ),
        headers=_mcp_headers(token),
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "NextProject Tech Platform"

    response = await client.post(
        "/mcp/tech-platform",
        json=_rpc("tools/list", request_id=2),
        headers=_mcp_headers(token),
    )
    assert response.status_code == 200, response.text
    names = {item["name"] for item in response.json()["result"]["tools"]}
    assert names == {
        "list_tech_platform_modules",
        "scan_tech_platform_modules",
        "preview_tech_platform_yaml",
        "validate_tech_platform_yaml",
        "deploy_tech_platform_module",
        "get_tech_platform_deploy_status",
    }


@pytest.mark.asyncio
async def test_mcp_tool_dispatch_is_scoped_and_never_logs_token(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, context_task_id, token = await _create_project_and_task(
        client, auth_headers
    )

    from backend.api import mcp_tech_platform

    module = {
        "id": "module-one",
        "site_id": "site-one",
        "site_name": "repo-one",
        "dockerfile_path": "Dockerfile",
        "build_context": ".",
        "app_name": "demo",
        "namespace": "user-maintained",
        "is_available": True,
        "status": "idle",
    }
    list_modules = AsyncMock(return_value=[module])
    scan_modules = AsyncMock(return_value=[module])
    preview_module = AsyncMock(return_value={"resources": [{"kind": "Deployment"}]})
    validate_module = AsyncMock(return_value={"valid": True, "resources": []})
    deploy_task = SimpleNamespace(
        id="deploy-task-one",
        project_id=project_id,
        site_id=None,
        title="deploy",
        task_type="deploy_tech_platform",
        status="queued",
        payload_json={},
        result_json={},
    )
    create_deploy_task = AsyncMock(return_value=deploy_task)
    append_log = AsyncMock()
    monkeypatch.setattr(
        mcp_tech_platform.tech_platform_deploy_service, "list_modules", list_modules
    )
    monkeypatch.setattr(
        mcp_tech_platform.tech_platform_deploy_service, "scan_modules", scan_modules
    )
    monkeypatch.setattr(
        mcp_tech_platform.tech_platform_deploy_service, "preview_module", preview_module
    )
    monkeypatch.setattr(
        mcp_tech_platform.tech_platform_deploy_service, "validate_module", validate_module
    )
    monkeypatch.setattr(
        mcp_tech_platform.tech_platform_deploy_service,
        "create_deploy_task",
        create_deploy_task,
    )
    monkeypatch.setattr(mcp_tech_platform.task_service, "append_log", append_log)

    calls = [
        ("list_tech_platform_modules", {}),
        ("scan_tech_platform_modules", {}),
        ("preview_tech_platform_yaml", {"module_id": "module-one", "image": "preview:v1"}),
        ("validate_tech_platform_yaml", {"module_id": "module-one"}),
        ("deploy_tech_platform_module", {"module_id": "module-one"}),
    ]
    for request_id, (name, arguments) in enumerate(calls, start=10):
        response = await client.post(
            "/mcp/tech-platform",
            json=_rpc(
                "tools/call",
                request_id=request_id,
                params={"name": name, "arguments": arguments},
            ),
            headers=_mcp_headers(token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["isError"] is False

    list_modules.assert_awaited_once()
    assert list_modules.await_args.args[1] == project_id
    scan_modules.assert_awaited_once()
    assert scan_modules.await_args.args[1] == project_id
    preview_module.assert_awaited_once()
    assert preview_module.await_args.args[1:4] == (
        project_id,
        "module-one",
        preview_module.await_args.args[3],
    )
    assert preview_module.await_args.args[4] == "preview:v1"
    validate_module.assert_awaited_once()
    assert validate_module.await_args.args[1] == project_id
    create_deploy_task.assert_awaited_once()
    assert create_deploy_task.await_args.args[1:3] == (project_id, "module-one")

    log_text = "\n".join(
        str(call.args[2]) for call in append_log.await_args_list if len(call.args) > 2
    )
    assert token not in log_text
    assert context_task_id not in log_text


@pytest.mark.asyncio
async def test_mcp_deploy_status_rejects_tasks_from_another_project(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, _, token = await _create_project_and_task(client, auth_headers)

    from backend.api import mcp_tech_platform

    other_task = SimpleNamespace(id="other-task", project_id="another-project")
    monkeypatch.setattr(
        mcp_tech_platform.task_service,
        "get_task",
        AsyncMock(return_value=other_task),
    )
    response = await client.post(
        "/mcp/tech-platform",
        json=_rpc(
            "tools/call",
            params={
                "name": "get_tech_platform_deploy_status",
                "arguments": {"task_id": "other-task"},
            },
        ),
        headers=_mcp_headers(token),
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == "部署任务不存在"
    assert project_id != other_task.project_id


@pytest.mark.asyncio
async def test_mcp_deploy_status_returns_incremental_logs(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, _, token = await _create_project_and_task(client, auth_headers)

    from backend.api import mcp_tech_platform

    deploy_task = SimpleNamespace(id="deploy-task", project_id=project_id)
    monkeypatch.setattr(
        mcp_tech_platform.task_service,
        "get_task",
        AsyncMock(return_value=deploy_task),
    )
    monkeypatch.setattr(
        mcp_tech_platform.task_service,
        "get_task_logs",
        AsyncMock(return_value=[{"id": 8, "line": "[deploy] success"}]),
    )
    monkeypatch.setattr(
        mcp_tech_platform.task_service,
        "serialize_task_detail",
        AsyncMock(return_value={"id": "deploy-task", "status": "running"}),
    )

    response = await client.post(
        "/mcp/tech-platform",
        json=_rpc(
            "tools/call",
            params={
                "name": "get_tech_platform_deploy_status",
                "arguments": {
                    "task_id": "deploy-task",
                    "after_log_id": 5,
                    "log_limit": 20,
                },
            },
        ),
        headers=_mcp_headers(token),
    )

    assert response.status_code == 200, response.text
    structured = response.json()["result"]["structuredContent"]
    assert structured["task"]["status"] == "running"
    assert structured["next_after_log_id"] == 8
    assert structured["logs"][0]["line"] == "[deploy] success"
