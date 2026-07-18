from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_project_conversation_defaults_to_all_repos(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Conversation Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    await client.post(
        f"/api/v2/projects/{project['id']}/repos",
        json={"name": "admin"},
        headers=auth_headers,
    )
    refreshed = await client.get(f"/api/v2/projects/{project['id']}", headers=auth_headers)
    repo_ids = [repo["site_id"] for repo in refreshed.json()["project"]["repos"]]

    response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={},
        headers=auth_headers,
    )

    assert response.status_code == 200
    conversation = response.json()["conversation"]
    assert conversation["scope_type"] == "project"
    assert conversation["project_id"] == project["id"]
    assert conversation["repo_ids"] == repo_ids

    list_response = await client.get(
        f"/api/v2/conversations/project/{project['id']}",
        headers=auth_headers,
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["conversations"]] == [conversation["id"]]


@pytest.mark.asyncio
async def test_project_conversation_send_message_creates_project_task_with_metadata(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    codex_provider,
    app_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.task_service import task_service

    monkeypatch.setattr(task_service, "enqueue_task", lambda task: None)

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Timeline Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    await codex_provider(project["id"])
    repo_id = project["repos"][0]["site_id"]
    conv_response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"repo_ids": [repo_id]},
        headers=auth_headers,
    )
    conv_id = conv_response.json()["conversation"]["id"]

    send_response = await client.post(
        f"/api/v2/conversations/{conv_id}/messages",
        json={"content": "把首页改成时间线开发入口", "provider": "codex", "repo_ids": [repo_id]},
        headers=auth_headers,
    )

    assert send_response.status_code == 200
    payload = send_response.json()
    assert payload["task"]["project_id"] == project["id"]
    assert payload["task"]["payload"]["conversation_id"] == conv_id
    assert payload["task"]["payload"]["repo_ids"] == [repo_id]
    assert payload["task"]["payload"]["prompt"] == "把首页改成时间线开发入口"
    assert "[系统提示]" not in payload["task"]["payload"]["prompt"]
    assert "[对话历史]" not in payload["task"]["payload"]["prompt"]
    assert payload["user_message"]["metadata"]["repo_ids"] == [repo_id]
    assert payload["assistant_message"]["message_type"] == "task_ref"
    assert payload["assistant_message"]["metadata"]["task_snapshot"]["id"] == payload["task_id"]

    detail = await client.get(f"/api/v2/conversations/{conv_id}", headers=auth_headers)
    conversation = detail.json()["conversation"]
    assert conversation["title"] == "把首页改成时间线开发入口"
    assert conversation["repo_ids"] == [repo_id]
    assert len(conversation["messages"]) == 2
    assert conversation["messages"][0]["metadata"]["project_id"] == project["id"]

    from backend.models.conversation import Conversation
    from backend.models.task import AgentTask

    async with app_module.AsyncSessionLocal() as db:
        task = await db.get(AgentTask, payload["task_id"])
        await task_service._persist_provider_session_id(db, task, "native-session-123")
        conv = await db.get(Conversation, conv_id)
        assert conv.provider_session_id == "native-session-123"

    follow_up = await client.post(
        f"/api/v2/conversations/{conv_id}/messages",
        json={"content": "只修改按钮文案", "provider": "codex", "repo_ids": [repo_id]},
        headers=auth_headers,
    )
    assert follow_up.status_code == 200, follow_up.text
    follow_up_payload = follow_up.json()["task"]["payload"]
    assert follow_up_payload["prompt"] == "只修改按钮文案"
    assert follow_up_payload["provider_session_id"] == "native-session-123"
    assert "把首页改成时间线开发入口" not in follow_up_payload["prompt"]


@pytest.mark.asyncio
async def test_project_conversation_rejects_codex_without_provider_before_saving_message(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Conversation Provider Required"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo_id = project["repos"][0]["site_id"]
    conv_response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"repo_ids": [repo_id]},
        headers=auth_headers,
    )
    conv_id = conv_response.json()["conversation"]["id"]

    send_response = await client.post(
        f"/api/v2/conversations/{conv_id}/messages",
        json={"content": "实现首页", "provider": "codex", "repo_ids": [repo_id]},
        headers=auth_headers,
    )
    assert send_response.status_code == 400
    assert "全局或项目级" in send_response.json()["detail"]
    assert "Codex Provider" in send_response.json()["detail"]

    detail = await client.get(f"/api/v2/conversations/{conv_id}", headers=auth_headers)
    assert detail.json()["conversation"]["messages"] == []


@pytest.mark.asyncio
async def test_project_conversation_uses_global_provider_without_project_override(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.task_service import task_service

    monkeypatch.setattr(task_service, "enqueue_task", lambda task: None)
    provider = await client.post(
        "/api/v2/providers",
        json={
            "name": "Global Codex Default",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-global-codex",
            "models": ["gpt-5-codex"],
            "formats": ["responses"],
            "enabled_formats": ["responses"],
            "scope_type": "global",
        },
        headers=auth_headers,
    )
    assert provider.status_code == 200, provider.text

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Global Provider Conversation"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo_id = project["repos"][0]["site_id"]
    conversation = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"repo_ids": [repo_id]},
        headers=auth_headers,
    )
    conv_id = conversation.json()["conversation"]["id"]

    sent = await client.post(
        f"/api/v2/conversations/{conv_id}/messages",
        json={"content": "使用全局配置实现首页", "provider": "codex", "repo_ids": [repo_id]},
        headers=auth_headers,
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["task"]["provider"] == "codex"


@pytest.mark.asyncio
async def test_project_conversation_rejects_repo_outside_project(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    first = await client.post(
        "/api/v2/projects",
        json={"name": "First Project"},
        headers=auth_headers,
    )
    second = await client.post(
        "/api/v2/projects",
        json={"name": "Second Project"},
        headers=auth_headers,
    )
    foreign_repo_id = second.json()["project"]["repos"][0]["site_id"]

    response = await client.post(
        f"/api/v2/conversations/project/{first.json()['project']['id']}",
        json={"repo_ids": [foreign_repo_id]},
        headers=auth_headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_project_conversation_archive_cannot_be_restored(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Archived Conversation Project"},
        headers=auth_headers,
    )
    project_id = create.json()["project"]["id"]
    conv_response = await client.post(
        f"/api/v2/conversations/project/{project_id}",
        json={"title": "可归档会话"},
        headers=auth_headers,
    )
    conv_id = conv_response.json()["conversation"]["id"]

    archive_response = await client.delete(f"/api/v2/conversations/{conv_id}", headers=auth_headers)
    assert archive_response.status_code == 200
    assert archive_response.json()["conversation"]["status"] == "archived"

    active_response = await client.get(f"/api/v2/conversations/project/{project_id}", headers=auth_headers)
    assert [item["id"] for item in active_response.json()["conversations"]] == []

    archived_response = await client.get(
        f"/api/v2/conversations/project/{project_id}",
        params={"status": "archived"},
        headers=auth_headers,
    )
    assert [item["id"] for item in archived_response.json()["conversations"]] == [conv_id]

    restore_response = await client.post(f"/api/v2/conversations/{conv_id}/restore", headers=auth_headers)
    assert restore_response.status_code == 409
    assert "不可恢复" in restore_response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("conversation_status", "completion_status"),
    [
        ("archived", "active"),
        ("archiving", "active"),
        ("active", "merging"),
        ("active", "completed"),
        ("active", "discarded"),
    ],
)
async def test_conversation_lifecycle_blocks_new_messages(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
    conversation_status: str,
    completion_status: str,
) -> None:
    from backend.models.conversation import Conversation

    create = await client.post(
        "/api/v2/projects",
        json={"name": f"Blocked Conversation {conversation_status} {completion_status}"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = response.json()["conversation"]
    async with app_module.AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conversation["id"])
        conv.status = conversation_status
        conv.completion_status = completion_status
        await db.commit()

    sent = await client.post(
        f"/api/v2/conversations/{conversation['id']}/messages",
        json={"content": "不应创建任务", "provider": "codex", "repo_ids": [repo["site_id"]]},
        headers=auth_headers,
    )

    assert sent.status_code == 409


@pytest.mark.asyncio
async def test_site_conversations_remain_site_scoped(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    site_response = await client.post(
        "/api/v2/sites",
        json={"site_id": "site-conv", "name": "Site Conv", "auto_start": False},
        headers=auth_headers,
    )
    site_id = site_response.json()["site"]["site_id"]

    create = await client.post(f"/api/v2/conversations/site/{site_id}", json={}, headers=auth_headers)
    assert create.status_code == 200
    assert create.json()["conversation"]["scope_type"] == "site"

    listed = await client.get(f"/api/v2/conversations/site/{site_id}", headers=auth_headers)
    assert listed.status_code == 200
    conversations = listed.json()["conversations"]
    assert len(conversations) == 1
    assert conversations[0]["scope_type"] == "site"
