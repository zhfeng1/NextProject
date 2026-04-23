from __future__ import annotations

import httpx
import pytest


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
async def test_add_blank_repo(client: httpx.AsyncClient, auth_headers: dict[str, str], app_module) -> None:
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
