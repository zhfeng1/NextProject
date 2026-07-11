from __future__ import annotations

import httpx
import pytest


async def _create_project(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    name: str,
) -> dict:
    response = await client.post(
        "/api/v2/projects",
        json={"name": name},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["project"]


async def _create_provider(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    *,
    name: str,
    formats: list[str],
    enabled_formats: list[str],
    scope_type: str = "project",
    project_id: str | None = None,
) -> dict:
    payload = {
        "name": name,
        "base_url": "https://api.example.com/v1",
        "api_key": f"sk-{name.lower().replace(' ', '-')}",
        "models": [f"model-{name.lower().replace(' ', '-')}"],
        "formats": formats,
        "enabled_formats": enabled_formats,
        "scope_type": scope_type,
        "is_default": True,
    }
    if project_id:
        payload["project_id"] = project_id
    response = await client.post(
        "/api/v2/providers",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["provider"]


@pytest.mark.asyncio
async def test_enabled_formats_are_unique_per_project_and_must_be_a_subset(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    first_project = await _create_project(client, auth_headers, "Provider Claims One")
    second_project = await _create_project(client, auth_headers, "Provider Claims Two")

    first = await _create_provider(
        client,
        auth_headers,
        name="First Project Provider",
        project_id=first_project["id"],
        formats=["responses", "messages"],
        enabled_formats=["responses", "messages"],
    )
    second = await _create_provider(
        client,
        auth_headers,
        name="Second Project Provider",
        project_id=first_project["id"],
        formats=["responses"],
        enabled_formats=["responses"],
    )
    other_project = await _create_provider(
        client,
        auth_headers,
        name="Other Project Provider",
        project_id=second_project["id"],
        formats=["responses"],
        enabled_formats=["responses"],
    )

    listed = await client.get(
        "/api/v2/providers",
        params={"scope_type": "project", "project_id": first_project["id"]},
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    by_id = {provider["id"]: provider for provider in listed.json()["providers"]}
    assert by_id[first["id"]]["enabled_formats"] == ["messages"]
    assert by_id[second["id"]]["enabled_formats"] == ["responses"]

    other_listed = await client.get(
        "/api/v2/providers",
        params={"scope_type": "project", "project_id": second_project["id"]},
        headers=auth_headers,
    )
    assert other_listed.status_code == 200, other_listed.text
    other_by_id = {provider["id"]: provider for provider in other_listed.json()["providers"]}
    assert other_by_id[other_project["id"]]["enabled_formats"] == ["responses"]

    invalid = await client.post(
        "/api/v2/providers",
        json={
            "name": "Invalid Enabled Format",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-invalid",
            "models": ["model-invalid"],
            "formats": ["messages"],
            "enabled_formats": ["responses"],
            "scope_type": "project",
            "project_id": first_project["id"],
        },
        headers=auth_headers,
    )
    assert invalid.status_code == 400
    assert "subset" in invalid.json()["detail"]


@pytest.mark.asyncio
async def test_programming_tools_prefer_project_providers_then_fallback_global_and_hide_claude(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.api.v2 import programming_tools as programming_tools_api

    async def healthy_adapter(tool_id: str):
        return True, {"ok": True, "cli_available": True, "version": f"test-{tool_id}"}

    monkeypatch.setattr(programming_tools_api.programming_tool_service, "adapter_health", healthy_adapter)

    project = await _create_project(client, auth_headers, "Programming Tool Metadata")
    global_responses = await _create_provider(
        client,
        auth_headers,
        name="Global Responses",
        scope_type="global",
        formats=["responses"],
        enabled_formats=["responses"],
    )
    messages = await _create_provider(
        client,
        auth_headers,
        name="Project Messages",
        project_id=project["id"],
        formats=["messages"],
        enabled_formats=["messages"],
    )
    chat = await _create_provider(
        client,
        auth_headers,
        name="Project Chat",
        project_id=project["id"],
        formats=["chat_completions"],
        enabled_formats=["chat_completions"],
    )

    metadata = await client.get(
        "/api/v2/programming-tools",
        params={"project_id": project["id"]},
        headers=auth_headers,
    )
    assert metadata.status_code == 200, metadata.text
    tools = {tool["id"]: tool for tool in metadata.json()["tools"]}
    assert list(tools) == ["codex", "codebuddy", "opencode", "kimi_code"]
    assert tools["codex"]["configured"] is True
    assert tools["codex"]["provider_id"] == global_responses["id"]
    assert tools["codex"]["provider_scope"] == "global"
    assert tools["codebuddy"]["selected_format"] == "messages"
    assert tools["codebuddy"]["provider_id"] == messages["id"]
    assert tools["codebuddy"]["provider_scope"] == "project"
    assert tools["opencode"]["selected_format"] == "messages"
    assert tools["opencode"]["provider_scope"] == "project"
    assert tools["kimi_code"]["selected_format"] == "messages"
    assert tools["kimi_code"]["provider_scope"] == "project"
    assert tools["codex"]["branch_prefix"] == "codex/"
    assert tools["codebuddy"]["branch_prefix"] == "codebuddy/"
    assert tools["opencode"]["branch_prefix"] == "opencode/"
    assert tools["kimi_code"]["branch_prefix"] == "kimi-code/"

    responses = await _create_provider(
        client,
        auth_headers,
        name="Project Responses",
        project_id=project["id"],
        formats=["responses"],
        enabled_formats=["responses"],
    )
    preferred = await client.get(
        "/api/v2/programming-tools",
        params={"project_id": project["id"]},
        headers=auth_headers,
    )
    preferred_tools = {tool["id"]: tool for tool in preferred.json()["tools"]}
    assert preferred_tools["codex"]["selected_format"] == "responses"
    assert preferred_tools["codebuddy"]["selected_format"] == "responses"
    assert preferred_tools["codebuddy"]["provider_id"] == responses["id"]
    assert preferred_tools["codebuddy"]["provider_scope"] == "project"
    assert preferred_tools["opencode"]["selected_format"] == "responses"
    assert preferred_tools["kimi_code"]["selected_format"] == "responses"

    disable_responses = await client.put(
        f"/api/v2/providers/{responses['id']}",
        json={"enabled_formats": []},
        headers=auth_headers,
    )
    assert disable_responses.status_code == 200, disable_responses.text
    disable_messages = await client.put(
        f"/api/v2/providers/{messages['id']}",
        json={"enabled_formats": []},
        headers=auth_headers,
    )
    assert disable_messages.status_code == 200, disable_messages.text

    fallback = await client.get(
        "/api/v2/programming-tools",
        params={"project_id": project["id"]},
        headers=auth_headers,
    )
    fallback_tools = {tool["id"]: tool for tool in fallback.json()["tools"]}
    assert fallback_tools["codex"]["configured"] is True
    assert fallback_tools["codex"]["provider_id"] == global_responses["id"]
    assert fallback_tools["codex"]["provider_scope"] == "global"
    assert fallback_tools["codebuddy"]["selected_format"] == "chat_completions"
    assert fallback_tools["codebuddy"]["provider_id"] == chat["id"]
    assert fallback_tools["codebuddy"]["provider_scope"] == "project"
    assert fallback_tools["opencode"]["selected_format"] == "chat_completions"
    assert fallback_tools["kimi_code"]["selected_format"] == "chat_completions"


@pytest.mark.asyncio
async def test_programming_tools_use_global_provider_when_project_has_no_override(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.api.v2 import programming_tools as programming_tools_api

    async def healthy_adapter(tool_id: str):
        return True, {"ok": True, "cli_available": True, "version": f"test-{tool_id}"}

    monkeypatch.setattr(programming_tools_api.programming_tool_service, "adapter_health", healthy_adapter)
    project = await _create_project(client, auth_headers, "Global Provider Fallback")
    global_provider = await _create_provider(
        client,
        auth_headers,
        name="Global Default Responses",
        scope_type="global",
        formats=["responses"],
        enabled_formats=["responses"],
    )

    metadata = await client.get(
        "/api/v2/programming-tools",
        params={"project_id": project["id"]},
        headers=auth_headers,
    )
    assert metadata.status_code == 200, metadata.text
    tools = {tool["id"]: tool for tool in metadata.json()["tools"]}
    assert list(tools) == ["codex", "codebuddy", "opencode", "kimi_code"]
    for tool in tools.values():
        assert tool["configured"] is True
        assert tool["selected_format"] == "responses"
        assert tool["provider_id"] == global_provider["id"]
        assert tool["provider_scope"] == "global"


@pytest.mark.asyncio
async def test_compatible_programming_tools_require_provider_base_url(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.api.v2 import programming_tools as programming_tools_api

    async def healthy_adapter(tool_id: str):
        return True, {"ok": True, "cli_available": True, "version": f"test-{tool_id}"}

    monkeypatch.setattr(programming_tools_api.programming_tool_service, "adapter_health", healthy_adapter)
    project = await _create_project(client, auth_headers, "Provider Base URL Required")
    response = await client.post(
        "/api/v2/providers",
        json={
            "name": "Missing Base URL",
            "base_url": "",
            "api_key": "sk-test",
            "models": ["test-model"],
            "formats": ["responses"],
            "enabled_formats": ["responses"],
            "scope_type": "project",
            "project_id": project["id"],
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    metadata = await client.get(
        "/api/v2/programming-tools",
        params={"project_id": project["id"]},
        headers=auth_headers,
    )
    tools = {tool["id"]: tool for tool in metadata.json()["tools"]}
    assert tools["codex"]["configured"] is True
    assert tools["codebuddy"]["configured"] is False
    assert tools["opencode"]["configured"] is False
    assert tools["kimi_code"]["configured"] is False
    assert tools["codebuddy"]["unavailable_reason"] == "未启用兼容的全局或项目级模型 Provider"
