from __future__ import annotations

import httpx
import pytest


async def _create_project_with_repos(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    project_name: str = "AI Center Project",
) -> tuple[dict, list[dict]]:
    project_response = await client.post(
        "/api/v2/projects",
        json={"name": project_name, "description": "test project"},
        headers=auth_headers,
    )
    assert project_response.status_code == 200
    project = project_response.json()["project"]

    repos: list[dict] = []
    for name in ("frontend", "backend"):
        repo_response = await client.post(
            f"/api/v2/projects/{project['id']}/repos",
            json={"name": name},
            headers=auth_headers,
        )
        assert repo_response.status_code == 200
        repos.append(repo_response.json()["repo"])
    return project, repos


@pytest.mark.asyncio
async def test_mcp_service_scope_configs_can_be_saved_and_tested(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    project, repos = await _create_project_with_repos(client, auth_headers, "MCP Scope Project")

    global_response = await client.put(
        "/api/v2/mcp/services/context7",
        json={"enabled": True, "scope_type": "global", "config": {"command": "npx", "args": ["-y", "@upstash/context7-mcp"]}},
        headers=auth_headers,
    )
    assert global_response.status_code == 200
    assert global_response.json()["service"]["scope_type"] == "global"

    project_response = await client.put(
        "/api/v2/mcp/services/context7",
        json={"enabled": True, "scope_type": "project", "project_id": project["id"], "config": {"command": "npx", "args": ["-y", "@upstash/context7-mcp"]}},
        headers=auth_headers,
    )
    assert project_response.status_code == 200
    assert project_response.json()["service"]["project_id"] == project["id"]

    repo_response = await client.put(
        "/api/v2/mcp/services/playwright",
        json={"enabled": True, "scope_type": "repo", "site_id": repos[0]["site_id"], "config": {"command": "npx", "args": ["-y", "@playwright/mcp"]}},
        headers=auth_headers,
    )
    assert repo_response.status_code == 200
    assert repo_response.json()["service"]["site_id"] == repos[0]["site_id"]

    list_response = await client.get(
        "/api/v2/mcp/services",
        params={"project_id": project["id"], "scope_type": "project"},
        headers=auth_headers,
    )
    assert list_response.status_code == 200
    assert [item["scope_type"] for item in list_response.json()["services"]] == ["project"]

    test_response = await client.post(
        "/api/v2/mcp/services/context7/test",
        json={"scope_type": "project", "project_id": project["id"]},
        headers=auth_headers,
    )
    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True


@pytest.mark.asyncio
async def test_skill_scope_import_and_site_resolution(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    project, repos = await _create_project_with_repos(client, auth_headers, "Skill Scope Project")

    create_response = await client.post(
        "/api/v2/skills",
        json={
            "name": "Repo Vue Helper",
            "description": "Repo only",
            "scope_type": "repo",
            "site_id": repos[0]["site_id"],
            "content": "# Repo Vue Helper\n\nUse Vue 3 composition APIs.",
            "triggers": ["vue"],
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert create_response.status_code == 200
    skill = create_response.json()["skill"]
    assert skill["scope_type"] == "repo"
    assert skill["site_id"] == repos[0]["site_id"]

    import_response = await client.post(
        "/api/v2/skills/import",
        json={
            "type": "markdown",
            "markdown": "# Project API Helper\n\nKeep OpenAPI docs in sync.",
            "scope_type": "project",
            "project_id": project["id"],
        },
        headers=auth_headers,
    )
    assert import_response.status_code == 200
    assert import_response.json()["skill"]["scope_type"] == "project"

    site_response = await client.get(f"/api/v2/skills/site/{repos[0]['site_id']}", headers=auth_headers)
    assert site_response.status_code == 200
    names = {item["name"] for item in site_response.json()["skills"]}
    assert {"Repo Vue Helper", "Project API Helper"} <= names


@pytest.mark.asyncio
async def test_project_task_creates_one_board_item_for_multiple_repos(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, repos = await _create_project_with_repos(client, auth_headers, "Task Board Project")
    monkeypatch.setattr(app_module.task_service, "enqueue_task", lambda task: None)

    create_response = await client.post(
        f"/api/v2/projects/{project['id']}/tasks",
        json={
            "repo_ids": [repo["site_id"] for repo in repos],
            "provider": "codex",
            "title": "Update frontend and backend auth",
            "prompt": "Adjust frontend and backend auth flow together.",
            "workflow_stages": ["research", "plan", "execute", "review"],
            "enabled_mcp_services": [],
            "enabled_skill_ids": [],
        },
        headers=auth_headers,
    )
    assert create_response.status_code == 200
    task = create_response.json()["task"]
    assert task["project_id"] == project["id"]
    assert task["board_status"] == "queued"
    assert task["workflow_stages"] == ["research", "plan", "execute", "review"]
    assert len(task["repositories"]) == 2

    board_response = await client.get(
        "/api/v2/tasks",
        params={"project_id": project["id"], "repo_id": repos[0]["site_id"], "keyword": "auth"},
        headers=auth_headers,
    )
    assert board_response.status_code == 200
    board_tasks = board_response.json()["tasks"]
    assert len(board_tasks) == 1
    assert board_tasks[0]["id"] == task["id"]

    blocked_response = await client.patch(
        f"/api/v2/tasks/{task['id']}/board-status",
        json={"board_status": "review"},
        headers=auth_headers,
    )
    assert blocked_response.status_code == 409

    cancel_response = await client.patch(
        f"/api/v2/tasks/{task['id']}/board-status",
        json={"board_status": "canceled"},
        headers=auth_headers,
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["task"]["board_status"] == "canceled"
