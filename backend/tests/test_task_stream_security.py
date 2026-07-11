from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


async def _create_task(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    codex_provider,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, dict]:
    from backend.services.task_service import task_service

    monkeypatch.setattr(task_service, "enqueue_task", lambda task: None)
    project_response = await client.post(
        "/api/v2/projects",
        json={"name": "Task Stream Security"},
        headers=auth_headers,
    )
    project = project_response.json()["project"]
    await codex_provider(project["id"])
    repo = project["repos"][0]
    conversation_response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "验证任务流", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = conversation_response.json()["conversation"]
    task_response = await client.post(
        f"/api/v2/conversations/{conversation['id']}/messages",
        json={"content": "只做任务流测试", "provider": "codex", "repo_ids": [repo["site_id"]]},
        headers=auth_headers,
    )
    assert task_response.status_code == 200, task_response.text
    return project, task_response.json()["task"]


@pytest.mark.asyncio
async def test_execution_details_are_incremental_and_redacted(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    codex_provider,
    app_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, task = await _create_task(client, auth_headers, codex_provider, monkeypatch)
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("TASK_ARTIFACTS_ROOT", str(artifacts_root))
    task_dir = artifacts_root / task["id"]
    task_dir.mkdir(parents=True)
    trace_path = task_dir / "codex-execution-trace.ndjson"
    trace_path.write_text(
        "\n".join([
            json.dumps({"seq": 1, "ts": "2026-07-15T00:00:00+00:00", "kind": "run_context", "content": "prompt sk-super-secret-key"}),
            json.dumps({"seq": 2, "ts": "2026-07-15T00:00:01+00:00", "kind": "cli_output", "content": "diff --git a/app.py b/app.py\\n+print('ok')"}),
        ]) + "\n",
        encoding="utf-8",
    )

    response = await client.get(
        f"/api/v2/tasks/{task['id']}/execution-details",
        params={"after_log_id": 0, "after_trace_seq": 0, "limit": 200},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    contents = "\n".join(item["content"] for item in payload["events"])
    assert "sk-super-secret-key" not in contents
    assert "[REDACTED]" in contents
    assert "diff --git" in contents
    assert payload["next_after_trace_seq"] == 2
    assert payload["redacted"] is True
    assert response.headers["cache-control"] == "no-store"

    empty = await client.get(
        f"/api/v2/tasks/{task['id']}/execution-details",
        params={
            "after_log_id": payload["next_after_log_id"],
            "after_trace_seq": payload["next_after_trace_seq"],
        },
        headers=auth_headers,
    )
    assert empty.status_code == 200
    assert empty.json()["events"] == []


@pytest.mark.asyncio
async def test_task_stream_ticket_is_task_bound_and_single_use(app_module) -> None:
    from backend.core.task_stream_ticket import task_stream_ticket_store

    ticket = await task_stream_ticket_store.issue(user_id="user-1", task_id="task-1")
    assert await task_stream_ticket_store.consume(ticket=ticket, task_id="task-2") is None
    assert await task_stream_ticket_store.consume(ticket=ticket, task_id="task-1") is None

    ticket = await task_stream_ticket_store.issue(user_id="user-1", task_id="task-1")
    payload = await task_stream_ticket_store.consume(ticket=ticket, task_id="task-1")
    assert payload is not None
    assert payload["user_id"] == "user-1"
    assert await task_stream_ticket_store.consume(ticket=ticket, task_id="task-1") is None


@pytest.mark.asyncio
async def test_websocket_rejects_missing_ticket(app_module) -> None:
    with TestClient(app_module.app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/tasks/task-without-ticket/logs"):
                pass
    assert exc_info.value.code == 4401
