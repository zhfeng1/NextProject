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
