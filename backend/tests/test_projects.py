from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select


async def _current_user(db):
    from backend.models import User

    result = await db.execute(select(User).where(User.email == "tester@example.com"))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_create_project(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    """PROJ-01: 创建项目成功"""
    response = await client.post(
        "/api/v2/projects",
        json={"name": "My Project", "description": "Test project"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["project"]["name"] == "My Project"
    assert payload["project"]["description"] == "Test project"
    assert "id" in payload["project"]
    assert len(payload["project"]["repos"]) == 1
    assert payload["project"]["repos"][0]["name"] == "app"


@pytest.mark.asyncio
async def test_create_project_default_repo_uses_python_vue_starter(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v2/projects",
        json={"name": "Starter Project"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    project = response.json()["project"]
    repo = project["repos"][0]
    from backend.services.project_service import project_service

    repo_root = project_service.repo_root(project["id"], "app")
    assert repo["config"]["source_type"] == "starter"
    assert repo["config"]["starter"] == "python-vue"
    assert repo["config"]["runtime"] == "python-fastapi"
    assert (repo_root / "backend" / "app.py").exists()
    assert (repo_root / "backend" / "requirements.txt").exists()
    assert (repo_root / "frontend" / "index.html").exists()
    assert (repo_root / "Dockerfile").exists()
    assert not (repo_root / ".openai").exists()
    assert (repo_root / "docs" / "README.md").exists()
    assert (repo_root / ".git").exists()


@pytest.mark.asyncio
async def test_create_project_can_skip_default_repo(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v2/projects",
        json={"name": "Empty Project", "create_default_repo": False},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["project"]["repos"] == []


@pytest.mark.asyncio
async def test_list_projects(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    """PROJ-01: 项目列表"""
    await client.post(
        "/api/v2/projects",
        json={"name": "List Project"},
        headers=auth_headers,
    )
    response = await client.get("/api/v2/projects", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert any(p["name"] == "List Project" for p in payload["projects"])


@pytest.mark.asyncio
async def test_list_projects_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v2/projects")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_site_without_project_id_still_works(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """PROJ-02: 向后兼容 — 无 project_id 的 Site 仍可正常创建"""
    response = await client.post(
        "/api/v2/sites",
        json={"site_id": "compat-site", "name": "Compat Site", "auto_start": False},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_codex_tasks_require_configured_provider(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Provider Required Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo_id = project["repos"][0]["site_id"]

    project_task = await client.post(
        f"/api/v2/projects/{project['id']}/tasks",
        json={"repo_ids": [repo_id], "provider": "codex", "prompt": "实现首页"},
        headers=auth_headers,
    )
    assert project_task.status_code == 400
    assert "全局或项目级" in project_task.json()["detail"]
    assert "Codex Provider" in project_task.json()["detail"]

    site_task = await client.post(
        "/api/v2/tasks",
        json={
            "site_id": repo_id,
            "task_type": "develop_code",
            "provider": "codex",
            "prompt": "实现首页",
        },
        headers=auth_headers,
    )
    assert site_task.status_code == 400
    assert "全局或项目级" in site_task.json()["detail"]
    assert "Codex Provider" in site_task.json()["detail"]

    board = await client.get(
        "/api/v2/tasks",
        params={"project_id": project["id"]},
        headers=auth_headers,
    )
    assert board.json()["tasks"] == []


@pytest.mark.asyncio
async def test_get_project(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Get Project"},
        headers=auth_headers,
    )
    project_id = create.json()["project"]["id"]
    response = await client.get(f"/api/v2/projects/{project_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["project"]["name"] == "Get Project"


@pytest.mark.asyncio
async def test_update_project(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Old Name"},
        headers=auth_headers,
    )
    project_id = create.json()["project"]["id"]
    response = await client.put(
        f"/api/v2/projects/{project_id}",
        json={"name": "New Name", "description": "Updated"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["project"]["name"] == "New Name"
    assert response.json()["project"]["description"] == "Updated"


@pytest.mark.asyncio
async def test_delete_project(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Delete Me"},
        headers=auth_headers,
    )
    project_id = create.json()["project"]["id"]
    del_resp = await client.delete(f"/api/v2/projects/{project_id}", headers=auth_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True
    # 删除后列表不再包含
    list_resp = await client.get("/api/v2/projects", headers=auth_headers)
    assert not any(p["id"] == project_id for p in list_resp.json()["projects"])


@pytest.mark.asyncio
async def test_add_blank_repo(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    """PROJ-03: 空白仓库创建"""
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Repo Project"},
        headers=auth_headers,
    )
    project_id = create.json()["project"]["id"]
    response = await client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "frontend"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["repo"]["name"] == "frontend"
    from backend.services.project_service import project_service

    repo_root = project_service.repo_root(project_id, "frontend")
    assert (repo_root / "backend" / "app.py").exists()
    assert (repo_root / "frontend" / "index.html").exists()
    assert not (repo_root / ".openai").exists()


@pytest.mark.asyncio
async def test_default_stack_prompt_only_for_first_empty_repo_task(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    codex_provider,
    app_module,
) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Prompt Project", "create_default_repo": False},
        headers=auth_headers,
    )
    project_id = create.json()["project"]["id"]
    await codex_provider(project_id)
    repo_resp = await client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "empty-repo", "starter": "empty"},
        headers=auth_headers,
    )
    repo_id = repo_resp.json()["repo"]["site_id"]

    from backend.services.site_service import site_service
    from backend.services.task_service import task_service

    async with app_module.AsyncSessionLocal() as db:
        current_user = await _current_user(db)
        task = await task_service.create_project_task(
            db,
            current_user,
            project_id,
            {"repo_ids": [repo_id], "provider": "codex", "prompt": "首次需求"},
            enqueue=False,
        )
        site = await site_service.get_site_by_public_id(db, repo_id, current_user)
        assert await task_service._should_include_default_stack_prompt(db, task, [site]) is True

        second_task = await task_service.create_project_task(
            db,
            current_user,
            project_id,
            {"repo_ids": [repo_id], "provider": "codex", "prompt": "第二次需求"},
            enqueue=False,
        )
        assert await task_service._should_include_default_stack_prompt(db, second_task, [site]) is False


@pytest.mark.asyncio
async def test_default_stack_prompt_not_added_for_python_vue_starter_task(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    codex_provider,
    app_module,
) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Starter Prompt Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    await codex_provider(project["id"])
    repo_id = project["repos"][0]["site_id"]

    from backend.services.site_service import site_service
    from backend.services.task_service import task_service

    async with app_module.AsyncSessionLocal() as db:
        current_user = await _current_user(db)
        task = await task_service.create_project_task(
            db,
            current_user,
            project["id"],
            {"repo_ids": [repo_id], "provider": "codex", "prompt": "需求"},
            enqueue=False,
        )
        site = await site_service.get_site_by_public_id(db, repo_id, current_user)
        assert await task_service._should_include_default_stack_prompt(db, task, [site]) is False


@pytest.mark.asyncio
async def test_develop_task_does_not_switch_selected_provider(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    codex_provider,
    app_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Provider Pin Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    await codex_provider(project["id"])
    repo_id = project["repos"][0]["site_id"]

    from backend.models.task import TaskStatus
    from backend.services.task_service import task_service

    async def fail_selected_provider(db, task_id: str):
        raise RuntimeError("codex auth missing")

    monkeypatch.setattr(task_service, "_run_develop_task_for_provider", fail_selected_provider)

    async with app_module.AsyncSessionLocal() as db:
        current_user = await _current_user(db)
        task = await task_service.create_project_task(
            db,
            current_user,
            project["id"],
            {"repo_ids": [repo_id], "provider": "codex", "prompt": "需求"},
            enqueue=False,
        )

        with pytest.raises(RuntimeError, match="codex auth missing"):
            await task_service.run_develop_task(db, str(task.id))

        await db.refresh(task)
        assert task.provider == "codex"
        assert task.status == TaskStatus.FAILED.value
        assert task.error == "codex auth missing"


@pytest.mark.asyncio
async def test_failed_project_task_can_be_retried(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    codex_provider,
    app_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Retry Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    await codex_provider(project["id"])
    repo_id = project["repos"][0]["site_id"]

    from backend.models.task import TaskStatus
    from backend.services.task_service import task_service

    enqueued: list[str] = []
    monkeypatch.setattr(task_service, "enqueue_task", lambda task: enqueued.append(str(task.id)))

    async with app_module.AsyncSessionLocal() as db:
        current_user = await _current_user(db)
        task = await task_service.create_project_task(
            db,
            current_user,
            project["id"],
            {"repo_ids": [repo_id], "provider": "codex", "prompt": "需求"},
            enqueue=False,
        )
        await task_service.update_status(db, task, TaskStatus.FAILED, error="boom")

        retried = await task_service.retry_task(db, str(task.id), current_user)

        assert retried.id == task.id
        assert retried.provider == "codex"
        assert retried.status == TaskStatus.QUEUED.value
        assert retried.board_status == "queued"
        assert retried.error == ""
        assert retried.started_at is None
        assert retried.finished_at is None
        assert enqueued == [str(task.id)]


@pytest.mark.asyncio
async def test_add_repo_invalid_name_rejected(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    """[ISSUE-04] 仓库名称含非法字符被拒绝"""
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Name Validation Project"},
        headers=auth_headers,
    )
    project_id = create.json()["project"]["id"]
    response = await client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "../evil-repo"},
        headers=auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_add_repo_slash_in_name_rejected(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    """[ISSUE-04] 仓库名称含斜杠被拒绝"""
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Slash Validation Project"},
        headers=auth_headers,
    )
    project_id = create.json()["project"]["id"]
    response = await client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "foo/bar"},
        headers=auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_repo_file_path_escape_blocked(client: httpx.AsyncClient, auth_headers: dict[str, str], app_module) -> None:
    """[ISSUE-07] 路径穿越防护：../不能逃逸出仓库根目录"""
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Path Escape Project"},
        headers=auth_headers,
    )
    project_id = create.json()["project"]["id"]
    repo_resp = await client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "test-repo"},
        headers=auth_headers,
    )
    repo_id = repo_resp.json()["repo"]["site_id"]

    # 尝试路径穿越读取文件
    escape_resp = await client.get(
        f"/api/v2/projects/{project_id}/repos/{repo_id}/file",
        params={"path": "../../etc/passwd"},
        headers=auth_headers,
    )
    assert escape_resp.status_code in (400, 403, 404)

    # 尝试路径穿越列出目录
    escape_list_resp = await client.get(
        f"/api/v2/projects/{project_id}/repos/{repo_id}/files",
        params={"path": "../../../"},
        headers=auth_headers,
    )
    assert escape_list_resp.status_code in (400, 403, 404)


@pytest.mark.asyncio
async def test_repo_files_cross_project_blocked(
    client: httpx.AsyncClient, auth_headers: dict[str, str], app_module
) -> None:
    """[NEW-03] 越权访问测试：用自己的 project_id 访问另一个项目的 repo 应返回 404"""
    # 创建项目 A 并添加仓库
    create_a = await client.post(
        "/api/v2/projects",
        json={"name": "Project A"},
        headers=auth_headers,
    )
    project_a_id = create_a.json()["project"]["id"]
    repo_a_resp = await client.post(
        f"/api/v2/projects/{project_a_id}/repos",
        json={"name": "repo-a"},
        headers=auth_headers,
    )
    repo_a_id = repo_a_resp.json()["repo"]["site_id"]

    # 创建项目 B（同一用户）
    create_b = await client.post(
        "/api/v2/projects",
        json={"name": "Project B"},
        headers=auth_headers,
    )
    project_b_id = create_b.json()["project"]["id"]

    # 使用项目 B 的 project_id 尝试访问项目 A 的 repo 文件列表 → 应返回 404
    cross_files_resp = await client.get(
        f"/api/v2/projects/{project_b_id}/repos/{repo_a_id}/files",
        headers=auth_headers,
    )
    assert cross_files_resp.status_code == 404

    # 使用项目 B 的 project_id 尝试读取项目 A 的 repo 文件 → 应返回 404
    cross_file_resp = await client.get(
        f"/api/v2/projects/{project_b_id}/repos/{repo_a_id}/file",
        params={"path": "index.html"},
        headers=auth_headers,
    )
    assert cross_file_resp.status_code == 404


@pytest.mark.asyncio
async def test_project_not_found(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/api/v2/projects/nonexistent-id", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_project_requires_name(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/v2/projects",
        json={"name": ""},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
