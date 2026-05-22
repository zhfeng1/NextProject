from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock

import httpx
import pytest


@pytest.mark.asyncio
async def test_list_site_tasks_filters_by_task_type(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """list_site_tasks 接受 task_type query 参数，按类型过滤。"""
    # 建项目
    res = await client.post(
        "/api/v2/projects",
        json={"name": "build-log-test"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    project_id = res.json()["project"]["id"]

    # 加 git 仓库 → 后端落库一条 clone_repo task（celery enqueue 在测试环境静默失败也无妨）
    res = await client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "repo-a", "git_url": "https://example.invalid/repo.git"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    site_id = res.json()["repo"]["site_id"]

    # 不过滤：至少包含那条 clone_repo
    res = await client.get(
        f"/api/v2/tasks/site/{site_id}",
        headers=auth_headers,
    )
    assert res.status_code == 200
    all_tasks = res.json()["tasks"]
    assert any(t["task_type"] == "clone_repo" for t in all_tasks)

    # 按 clone_repo 过滤
    res = await client.get(
        f"/api/v2/tasks/site/{site_id}?task_type=clone_repo",
        headers=auth_headers,
    )
    filtered = res.json()["tasks"]
    assert filtered, "filtered list should not be empty"
    assert all(t["task_type"] == "clone_repo" for t in filtered)

    # 过滤不存在的类型：空列表
    res = await client.get(
        f"/api/v2/tasks/site/{site_id}?task_type=develop_code",
        headers=auth_headers,
    )
    assert res.json()["tasks"] == []
