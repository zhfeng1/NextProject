from __future__ import annotations

from unittest.mock import patch, MagicMock

import httpx
import pytest


@pytest.mark.asyncio
async def test_list_site_tasks_filters_by_task_type(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """list_site_tasks 接受 task_type query 参数，按类型过滤。"""
    res = await client.post(
        "/api/v2/projects",
        json={"name": "build-log-test"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    project_id = res.json()["project"]["id"]

    res = await client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "repo-a", "git_url": "https://example.invalid/repo.git"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    site_id = res.json()["repo"]["site_id"]

    res = await client.get(
        f"/api/v2/tasks/site/{site_id}",
        headers=auth_headers,
    )
    assert res.status_code == 200
    all_tasks = res.json()["tasks"]
    assert any(t["task_type"] == "clone_repo" for t in all_tasks)

    res = await client.get(
        f"/api/v2/tasks/site/{site_id}?task_type=clone_repo",
        headers=auth_headers,
    )
    filtered = res.json()["tasks"]
    assert filtered, "filtered list should not be empty"
    assert all(t["task_type"] == "clone_repo" for t in filtered)

    res = await client.get(
        f"/api/v2/tasks/site/{site_id}?task_type=develop_code",
        headers=auth_headers,
    )
    assert res.json()["tasks"] == []


def _make_popen_mock(stdout_lines: list[str], returncode: int) -> MagicMock:
    """构造 Popen 替身：stdout 是可迭代的行序列，wait() 返回指定 rc。"""
    proc = MagicMock()
    proc.stdout = iter(stdout_lines)
    proc.wait.return_value = returncode
    proc.returncode = returncode
    proc.poll.return_value = returncode  # 防止 finally 块 kill 假进程
    return proc


async def _create_clone_task(client: httpx.AsyncClient, auth_headers: dict[str, str], name: str) -> tuple[str, str]:
    """辅助：建项目+加 git 仓库，返回 (site_id_public, task_id)。"""
    res = await client.post("/api/v2/projects", json={"name": name}, headers=auth_headers)
    project_id = res.json()["project"]["id"]
    res = await client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "repo", "git_url": "https://example.invalid/x.git"},
        headers=auth_headers,
    )
    site_id_public = res.json()["repo"]["site_id"]
    res = await client.get(
        f"/api/v2/tasks/site/{site_id_public}?task_type=clone_repo",
        headers=auth_headers,
    )
    task_id = res.json()["tasks"][0]["id"]
    return site_id_public, task_id


@pytest.mark.asyncio
async def test_clone_repo_task_writes_progress_logs_on_success(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """成功路径：git 每行 stdout 都落进 agent_task_logs，且最后 site=stopped。"""
    site_id_public, task_id = await _create_clone_task(client, auth_headers, "log-stream")

    popen_mock = _make_popen_mock(
        ["Cloning into 'repo'...\n", "remote: Counting objects: 10\n", "Receiving objects: 100%\n"],
        returncode=0,
    )

    # Mock Popen + lock + filesystem-touching helpers; .git existence stubbed True
    from pathlib import Path as _Path
    real_exists = _Path.exists

    def fake_exists(self: _Path) -> bool:
        # 让 .git 子路径校验通过；其他真实路径（项目目录/tmp 等）走真实逻辑
        if self.name == ".git":
            return True
        return real_exists(self)

    with patch("backend.tasks.clone_repo.subprocess.Popen", return_value=popen_mock), \
         patch(
             "backend.tasks.clone_repo.subprocess.run",
             return_value=MagicMock(returncode=0, stdout="main\n", stderr=""),
         ), \
         patch("backend.tasks.clone_repo.acquire_site_lock", return_value=True), \
         patch("backend.tasks.clone_repo.release_site_lock"), \
         patch("backend.services.site_service.SiteService._ensure_docs_structure"), \
         patch("backend.services.site_service.SiteService._ensure_np_structure"), \
         patch.object(_Path, "exists", fake_exists):
        from backend.tasks.clone_repo import _run_clone
        await _run_clone(task_id)

    res = await client.get(f"/api/v2/tasks/{task_id}/logs", headers=auth_headers)
    lines = [l["line"] for l in res.json()["logs"]]
    assert any("开始克隆" in l for l in lines), f"expect 开始克隆 log, got: {lines}"
    assert any("Cloning into" in l for l in lines), f"expect git output captured, got: {lines}"
    assert any("克隆完成" in l for l in lines), f"expect 克隆完成 log, got: {lines}"


@pytest.mark.asyncio
async def test_clone_repo_task_writes_error_log_on_failure(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """失败路径：rc != 0 时写 ERROR 日志，site=error。"""
    site_id_public, task_id = await _create_clone_task(client, auth_headers, "log-fail")

    popen_mock = _make_popen_mock(
        ["fatal: repository not found\n"],
        returncode=128,
    )

    with patch("backend.tasks.clone_repo.subprocess.Popen", return_value=popen_mock), \
         patch("backend.tasks.clone_repo.acquire_site_lock", return_value=True), \
         patch("backend.tasks.clone_repo.release_site_lock"):
        from backend.tasks.clone_repo import _run_clone
        with pytest.raises(RuntimeError, match="退出码"):
            await _run_clone(task_id)

    res = await client.get(f"/api/v2/tasks/{task_id}/logs", headers=auth_headers)
    log_levels = [(l["level"], l["line"]) for l in res.json()["logs"]]
    assert any(lvl == "ERROR" for lvl, _ in log_levels), f"expect ERROR log, got: {log_levels}"

    res = await client.get(f"/api/v2/sites/{site_id_public}", headers=auth_headers)
    assert res.json()["site"]["status"] == "error"
