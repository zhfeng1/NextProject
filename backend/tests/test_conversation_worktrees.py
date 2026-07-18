from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest


GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def test_task_cwd_uses_single_repo_but_preserves_multi_repo_and_completion_roots() -> None:
    from backend.services.task_service import TaskService

    workspace_root = "/generated_sites/project/.worktree/conversation"
    first_repo = SimpleNamespace(repo_path=f"{workspace_root}/app")
    second_repo = SimpleNamespace(repo_path=f"{workspace_root}/api")
    develop_task = SimpleNamespace(
        payload_json={"workspace_root": workspace_root},
        project_id="project",
    )
    completion_task = SimpleNamespace(
        payload_json={"workspace_root": "/generated_sites/project", "completion_mode": True},
        project_id="project",
    )

    assert TaskService._project_root_for_task(develop_task, task_repos=[first_repo]) == Path(first_repo.repo_path)
    assert TaskService._project_root_for_task(
        develop_task,
        task_repos=[first_repo, second_repo],
    ) == Path(workspace_root)
    assert TaskService._project_root_for_task(
        completion_task,
        task_repos=[SimpleNamespace(repo_path="/generated_sites/project/app")],
    ) == Path("/generated_sites/project")


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=GIT_ENV,
        check=True,
    )
    return result.stdout.strip()


def test_git_history_rejects_repository_symlink_outside_project(tmp_path: Path) -> None:
    from fastapi import HTTPException
    from backend.services.git_history_service import git_history_service

    project_root = tmp_path / "project"
    project_root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    repo_path = project_root / "repo"
    repo_path.symlink_to(external, target_is_directory=True)

    with pytest.raises(HTTPException, match="超出项目边界"):
        git_history_service.ensure_repository_path(repo_path, boundary=project_root)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "expected_prefix"),
    [("codebuddy", "codebuddy/"), ("opencode", "opencode/"), ("kimi_code", "kimi-code/")],
)
async def test_conversation_branch_uses_programming_tool_prefix(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    provider: str,
    expected_prefix: str,
) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": f"{provider} Branch Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]

    response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "实现项目看板", "repo_ids": [repo["site_id"]], "provider": provider},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    branch_name = response.json()["conversation"]["branch_name"]
    assert branch_name == f"{expected_prefix}实现项目看板"


@pytest.mark.asyncio
async def test_conversation_creates_worktree_from_configured_main_branch_and_reports_diff(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    from backend.services.project_service import project_service

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Worktree Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    repo_root = project_service.repo_root(project["id"], repo["name"])
    run_git(repo_root, "branch", "dev")

    update = await client.put(
        f"/api/v2/projects/{project['id']}/repos/{repo['site_id']}/main-branch",
        json={"main_branch": "dev"},
        headers=auth_headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["repo"]["main_branch"] == "dev"

    response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "优化登录页", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    conversation = response.json()["conversation"]
    assert conversation["branch_name"] == "codex/优化登录页"
    worktree_root = Path(conversation["worktree_root"])
    worktree_repo = worktree_root / repo["name"]
    assert worktree_root.parent.name == ".worktree"
    assert worktree_repo.exists()
    assert run_git(worktree_repo, "branch", "--show-current") == conversation["branch_name"]

    changed_file = worktree_repo / "worktree-change.txt"
    changed_file.write_text("worktree only\n", encoding="utf-8")
    run_git(worktree_repo, "add", "worktree-change.txt")
    run_git(worktree_repo, "commit", "-m", "Add worktree change")

    state_response = await client.get(
        f"/api/v2/conversations/{conversation['id']}/git",
        headers=auth_headers,
    )
    assert state_response.status_code == 200, state_response.text
    state = state_response.json()["git"]
    repo_state = state["repositories"][0]
    assert repo_state["main_branch"] == "dev"
    assert repo_state["branch_name"] == "codex/优化登录页"
    assert repo_state["ahead"] == 1
    assert repo_state["behind"] == 0
    assert repo_state["changed_files"] == 1
    assert "worktree-change.txt" in repo_state["diff"]
    assert not (repo_root / "worktree-change.txt").exists()


@pytest.mark.asyncio
async def test_project_git_graph_defaults_to_main_supports_branch_selection_and_rollback(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    from backend.models.repo_git_operation import RepoGitOperation
    from backend.models.site import Site
    from backend.models.task import AgentTask, TaskStatus
    from backend.services.project_service import project_service
    from sqlalchemy import select

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Git Graph Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    repo_root = project_service.repo_root(project["id"], repo["name"])
    main_branch = run_git(repo_root, "branch", "--show-current")
    first_sha = run_git(repo_root, "rev-parse", "HEAD")

    (repo_root / "graph-change.txt").write_text("graph\n", encoding="utf-8")
    run_git(repo_root, "add", "graph-change.txt")
    run_git(repo_root, "commit", "-m", "Add graph change")
    second_sha = run_git(repo_root, "rev-parse", "HEAD")
    run_git(repo_root, "branch", "feature/history", first_sha)

    response = await client.get(
        f"/api/v2/projects/{project['id']}/repos/{repo['site_id']}/git/graph",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    graph = response.json()["graph"]
    assert graph["branch"] == main_branch
    assert graph["default_branch"] == main_branch
    assert graph["head_sha"] == second_sha
    assert graph["commits"][0]["current"] is True
    assert graph["commits"][0]["parents"] == [first_sha]
    assert isinstance(graph["commits"][0]["lane"], int)
    local_branches = {
        item["name"] for item in graph["branches"] if item["type"] == "local_branch"
    }
    assert {main_branch, "feature/history"}.issubset(local_branches)

    feature_response = await client.get(
        f"/api/v2/projects/{project['id']}/repos/{repo['site_id']}/git/graph",
        params={"branch": "feature/history"},
        headers=auth_headers,
    )
    assert feature_response.status_code == 200, feature_response.text
    feature_graph = feature_response.json()["graph"]
    assert feature_graph["branch"] == "feature/history"
    assert feature_graph["head_sha"] == first_sha
    assert feature_graph["default_branch"] == main_branch
    assert feature_graph["commits"][0]["sha"] == first_sha
    assert second_sha not in {commit["sha"] for commit in feature_graph["commits"]}

    missing = await client.get(
        f"/api/v2/projects/{project['id']}/repos/{repo['site_id']}/git/graph",
        params={"branch": "missing-branch"},
        headers=auth_headers,
    )
    assert missing.status_code == 404

    async with app_module.AsyncSessionLocal() as db:
        site = (await db.execute(select(Site).where(Site.site_id == repo["site_id"]))).scalar_one()
        db.add(AgentTask(
            id="queued-project-rollback-task",
            site_id=site.id,
            project_id=project["id"],
            task_type="develop_code",
            status=TaskStatus.QUEUED.value,
            payload_json={},
        ))
        await db.commit()

    task_blocked = await client.post(
        f"/api/v2/projects/{project['id']}/repos/{repo['site_id']}/git/rollback",
        json={"commit_sha": first_sha},
        headers=auth_headers,
    )
    assert task_blocked.status_code == 409
    assert "排队中或运行中" in task_blocked.json()["detail"]

    async with app_module.AsyncSessionLocal() as db:
        task = await db.get(AgentTask, "queued-project-rollback-task")
        task.status = TaskStatus.CANCELED.value
        await db.commit()

    rollback = await client.post(
        f"/api/v2/projects/{project['id']}/repos/{repo['site_id']}/git/rollback",
        json={"commit_sha": first_sha, "branch": main_branch},
        headers=auth_headers,
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["operation"]["before_sha"] == second_sha
    assert rollback.json()["operation"]["after_sha"] == first_sha
    assert rollback.json()["operation"]["status"] == "success"
    assert run_git(repo_root, "rev-parse", main_branch) == first_sha
    assert not (repo_root / "graph-change.txt").exists()

    async with app_module.AsyncSessionLocal() as db:
        rows = await db.execute(select(RepoGitOperation))
        operations = list(rows.scalars().all())
        assert len(operations) == 1
        assert operations[0].scope == "project"
        assert operations[0].status == "success"


@pytest.mark.asyncio
async def test_project_git_rollback_rejects_dirty_tree_and_persists_failure(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    from backend.models.repo_git_operation import RepoGitOperation
    from backend.services.project_service import project_service
    from sqlalchemy import select

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Dirty Rollback Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    repo_root = project_service.repo_root(project["id"], repo["name"])
    head_sha = run_git(repo_root, "rev-parse", "HEAD")
    (repo_root / "untracked.txt").write_text("preserve\n", encoding="utf-8")

    response = await client.post(
        f"/api/v2/projects/{project['id']}/repos/{repo['site_id']}/git/rollback",
        json={"commit_sha": head_sha},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert "未提交或未跟踪" in response.json()["detail"]
    assert (repo_root / "untracked.txt").exists()

    async with app_module.AsyncSessionLocal() as db:
        operation = (await db.execute(select(RepoGitOperation))).scalar_one()
        assert operation.status == "failed"
        assert "未提交或未跟踪" in operation.error


@pytest.mark.asyncio
async def test_conversation_git_graph_and_task_branch_rollback_follow_lifecycle(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    from backend.models.conversation import Conversation
    from backend.models.repo_git_operation import RepoGitOperation
    from backend.models.task import AgentTask, TaskStatus
    from sqlalchemy import select

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Conversation Graph Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    conv_response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "展示任务分支图", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = conv_response.json()["conversation"]
    worktree = Path(conversation["worktree_root"]) / repo["name"]
    baseline_sha = run_git(worktree, "rev-parse", "HEAD")
    (worktree / "conversation-graph.txt").write_text("task graph\n", encoding="utf-8")
    run_git(worktree, "add", "conversation-graph.txt")
    run_git(worktree, "commit", "-m", "Add conversation graph change")
    task_sha = run_git(worktree, "rev-parse", "HEAD")

    graph_response = await client.get(
        f"/api/v2/conversations/{conversation['id']}/repos/{repo['site_id']}/git/graph",
        headers=auth_headers,
    )
    assert graph_response.status_code == 200, graph_response.text
    graph = graph_response.json()["graph"]
    assert graph["scope"] == "conversation"
    assert graph["branch"] == conversation["branch_name"]
    assert graph["head_sha"] == task_sha
    current = next(item for item in graph["commits"] if item["current"])
    assert current["sha"] == task_sha
    assert any(
        label["name"] == conversation["branch_name"] and label["current"]
        for label in current["labels"]
    )

    async with app_module.AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conversation["id"])
        task = AgentTask(
            id="queued-rollback-task",
            site_id=conv.site_id,
            project_id=project["id"],
            conversation_id=conversation["id"],
            task_type="develop_code",
            status=TaskStatus.QUEUED.value,
            payload_json={"conversation_id": conversation["id"]},
        )
        db.add(task)
        await db.commit()

    running_blocked = await client.post(
        f"/api/v2/conversations/{conversation['id']}/repos/{repo['site_id']}/git/rollback",
        json={"commit_sha": baseline_sha},
        headers=auth_headers,
    )
    assert running_blocked.status_code == 409
    assert "排队中或运行中" in running_blocked.json()["detail"]

    async with app_module.AsyncSessionLocal() as db:
        task = await db.get(AgentTask, "queued-rollback-task")
        task.status = TaskStatus.CANCELED.value
        await db.commit()

    rollback = await client.post(
        f"/api/v2/conversations/{conversation['id']}/repos/{repo['site_id']}/git/rollback",
        json={"commit_sha": baseline_sha},
        headers=auth_headers,
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["operation"]["scope"] == "conversation"
    assert rollback.json()["operation"]["before_sha"] == task_sha
    assert rollback.json()["operation"]["after_sha"] == baseline_sha
    assert run_git(worktree, "rev-parse", "HEAD") == baseline_sha
    assert not (worktree / "conversation-graph.txt").exists()

    async with app_module.AsyncSessionLocal() as db:
        operation = (await db.execute(select(RepoGitOperation))).scalar_one()
        assert operation.status == "success"
        conv = await db.get(Conversation, conversation["id"])
        assert conv.git_repos_json[0]["branch_tip_sha"] == baseline_sha
        conv.completion_status = "completed"
        await db.commit()

    blocked = await client.post(
        f"/api/v2/conversations/{conversation['id']}/repos/{repo['site_id']}/git/rollback",
        json={"commit_sha": baseline_sha},
        headers=auth_headers,
    )
    assert blocked.status_code == 409
    assert "已结束" in blocked.json()["detail"]


@pytest.mark.asyncio
async def test_failed_conversation_cannot_rollback_after_changes_enter_main_branch(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    from backend.models.conversation import Conversation
    from backend.services.project_service import project_service

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Failed Merge Rollback Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    conv_response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "模拟合并后推送失败", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = conv_response.json()["conversation"]
    worktree = Path(conversation["worktree_root"]) / repo["name"]
    baseline_sha = run_git(worktree, "rev-parse", "HEAD")
    (worktree / "merged-before-push-failure.txt").write_text("merged\n", encoding="utf-8")
    run_git(worktree, "add", "merged-before-push-failure.txt")
    run_git(worktree, "commit", "-m", "Change merged before push failure")

    main_repo = project_service.repo_root(project["id"], repo["name"])
    run_git(
        main_repo,
        "merge",
        "--no-ff",
        conversation["branch_name"],
        "-m",
        "Merge before simulated push failure",
    )
    async with app_module.AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conversation["id"])
        conv.completion_status = "failed"
        conv.completion_error = "push failed"
        await db.commit()

    response = await client.post(
        f"/api/v2/conversations/{conversation['id']}/repos/{repo['site_id']}/git/rollback",
        json={"commit_sha": baseline_sha},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert "进入主分支" in response.json()["detail"]
    assert run_git(worktree, "rev-parse", "HEAD") != baseline_sha


@pytest.mark.asyncio
async def test_conversation_task_uses_worktree_and_completion_task_uses_main_repo(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    codex_provider,
    app_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.task_service import task_service

    enqueued: list[str] = []
    monkeypatch.setattr(task_service, "enqueue_task", lambda task: enqueued.append(str(task.id)))
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Completion Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    await codex_provider(project["id"])
    repo = project["repos"][0]
    conv_response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "增加个人中心", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = conv_response.json()["conversation"]

    send = await client.post(
        f"/api/v2/conversations/{conversation['id']}/messages",
        json={"content": "增加个人中心", "provider": "codex", "repo_ids": [repo["site_id"]]},
        headers=auth_headers,
    )
    assert send.status_code == 200, send.text
    develop_task = send.json()["task"]
    assert develop_task["payload"]["workspace_root"] == conversation["worktree_root"]
    assert develop_task["repositories"][0]["repo_path"].startswith(conversation["worktree_root"])
    enqueued.clear()

    from backend.models.task import AgentTask
    async with app_module.AsyncSessionLocal() as db:
        task = await db.get(AgentTask, send.json()["task_id"])
        task.status = "success"
        await db.commit()

    complete = await client.post(
        f"/api/v2/conversations/{conversation['id']}/complete",
        headers=auth_headers,
    )
    assert complete.status_code == 200, complete.text
    payload = complete.json()
    assert payload["conversation"]["completion_status"] == "merging"
    assert payload["task"]["payload"]["completion_mode"] is True
    assert ".worktree" not in payload["task"]["payload"]["workspace_root"]
    assert ".worktree" not in payload["task"]["repositories"][0]["repo_path"]
    assert payload["assistant_message"]["metadata"]["completion_mode"] is True
    assert enqueued == [payload["task_id"]]
    async with app_module.AsyncSessionLocal() as db:
        completion_task = await db.get(AgentTask, payload["task_id"])
        assert completion_task.conversation_id == conversation["id"]


@pytest.mark.asyncio
async def test_single_repo_conversation_runs_adapter_inside_repo_worktree(
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
        json={"name": "Single Repo CWD Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    await codex_provider(project["id"])
    repo = project["repos"][0]
    conversation_response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "仅修改仓库内文件", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = conversation_response.json()["conversation"]
    sent = await client.post(
        f"/api/v2/conversations/{conversation['id']}/messages",
        json={"content": "新增说明文件", "provider": "codex", "repo_ids": [repo["site_id"]]},
        headers=auth_headers,
    )
    assert sent.status_code == 200, sent.text
    task_id = sent.json()["task_id"]
    captured: dict[str, object] = {}

    async def fake_adapter_stream(db, task, *, provider, request_payload, display_path):
        del db, task, provider, display_path
        captured.update(request_payload)
        return 0, "完成", {"usage": {}, "diagnostic": ""}

    monkeypatch.setattr(task_service, "_run_adapter_stream", fake_adapter_stream)
    async with app_module.AsyncSessionLocal() as db:
        await task_service._run_develop_task_for_provider(db, task_id)

    expected_cwd = Path(conversation["worktree_root"]) / repo["name"]
    assert captured["cwd"] == str(expected_cwd)
    assert "当前工作目录就是唯一参与仓库" in str(captured["prompt"])
    assert "不要在父目录或会话 worktree 根目录创建文件" in str(captured["prompt"])


@pytest.mark.asyncio
async def test_archiving_project_conversation_snapshots_and_discards_worktree(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    from backend.services.project_service import project_service

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Archive Cleanup Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    conversation_response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "归档并丢弃", "repo_ids": [repo["site_id"]], "provider": "codebuddy"},
        headers=auth_headers,
    )
    conversation = conversation_response.json()["conversation"]
    worktree_root = Path(conversation["worktree_root"])
    worktree_repo = worktree_root / repo["name"]
    branch_name = conversation["branch_name"]
    (worktree_repo / "discarded-change.txt").write_text("discard me\n", encoding="utf-8")
    run_git(worktree_repo, "add", "discarded-change.txt")
    run_git(worktree_repo, "commit", "-m", "Add discarded change")

    archived = await client.delete(
        f"/api/v2/conversations/{conversation['id']}",
        headers=auth_headers,
    )

    assert archived.status_code == 200, archived.text
    payload = archived.json()["conversation"]
    assert payload["status"] == "archived"
    assert payload["completion_status"] == "discarded"
    assert payload["cleanup_status"] == "cleaned"
    assert not worktree_root.exists()
    main_repo = project_service.repo_root(project["id"], repo["name"])
    branch = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=str(main_repo),
        check=False,
    )
    assert branch.returncode != 0

    state_response = await client.get(
        f"/api/v2/conversations/{conversation['id']}/git",
        headers=auth_headers,
    )
    state = state_response.json()["git"]
    assert state["available"] is True
    assert state["live_available"] is False
    assert state["deleted"] is True
    assert state["read_only"] is True
    assert state["repositories"][0]["snapshot"] is True
    assert state["repositories"][0]["branch_deleted"] is True
    assert state["repositories"][0]["worktree_deleted"] is True
    assert state["repositories"][0]["read_only"] is True
    assert "discarded-change.txt" in state["repositories"][0]["diff"]


@pytest.mark.asyncio
async def test_completed_conversation_cleanup_removes_merged_branch_non_force(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    from backend.models.conversation import Conversation
    from backend.services.project_service import project_service

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Completed Cleanup Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    conversation_response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "完成后清理", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = conversation_response.json()["conversation"]
    worktree_root = Path(conversation["worktree_root"])
    worktree_repo = worktree_root / repo["name"]
    branch_name = conversation["branch_name"]
    (worktree_repo / "merged-change.txt").write_text("merged\n", encoding="utf-8")
    run_git(worktree_repo, "add", "merged-change.txt")
    run_git(worktree_repo, "commit", "-m", "Add merged change")
    from backend.services.conversation_git_service import conversation_git_service
    async with app_module.AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conversation["id"])
        conv.git_repos_json = conversation_git_service.capture_repository_tips(
            list(conv.git_repos_json or []),
            require_clean=True,
        )
        await db.commit()
    main_repo = project_service.repo_root(project["id"], repo["name"])
    run_git(main_repo, "merge", "--no-ff", branch_name, "-m", "Merge completed conversation")
    async with app_module.AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conversation["id"])
        conv.completion_status = "completed"
        await db.commit()

    cleanup = await client.post(
        f"/api/v2/conversations/{conversation['id']}/cleanup",
        headers=auth_headers,
    )

    assert cleanup.status_code == 200, cleanup.text
    assert cleanup.json()["conversation"]["completion_status"] == "completed"
    assert cleanup.json()["conversation"]["cleanup_status"] == "cleaned", cleanup.json()
    assert cleanup.json()["git"]["available"] is True
    assert cleanup.json()["git"]["live_available"] is False
    assert cleanup.json()["git"]["deleted"] is True
    assert cleanup.json()["git"]["read_only"] is True
    assert not worktree_root.exists()
    branch = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=str(main_repo),
        check=False,
    )
    assert branch.returncode != 0


@pytest.mark.asyncio
async def test_completed_cleanup_warning_does_not_change_completion_status(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    from backend.models.conversation import Conversation
    from backend.services.project_service import project_service

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Cleanup Warning Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "保留清理告警", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = response.json()["conversation"]
    worktree_root = Path(conversation["worktree_root"])
    worktree_repo = worktree_root / repo["name"]
    branch_name = conversation["branch_name"]
    (worktree_repo / "warning-change.txt").write_text("merged\n", encoding="utf-8")
    run_git(worktree_repo, "add", "warning-change.txt")
    run_git(worktree_repo, "commit", "-m", "Add warning change")
    from backend.services.conversation_git_service import conversation_git_service
    async with app_module.AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conversation["id"])
        conv.git_repos_json = conversation_git_service.capture_repository_tips(
            list(conv.git_repos_json or []),
            require_clean=True,
        )
        await db.commit()
    main_repo = project_service.repo_root(project["id"], repo["name"])
    run_git(main_repo, "merge", "--no-ff", branch_name, "-m", "Merge warning conversation")
    (worktree_root / "unexpected-root-file.txt").write_text("preserve for warning\n", encoding="utf-8")
    async with app_module.AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conversation["id"])
        conv.completion_status = "completed"
        await db.commit()

    cleanup = await client.post(
        f"/api/v2/conversations/{conversation['id']}/cleanup",
        headers=auth_headers,
    )

    assert cleanup.status_code == 200, cleanup.text
    payload = cleanup.json()["conversation"]
    assert payload["completion_status"] == "completed"
    assert payload["cleanup_status"] == "warning"
    assert payload["cleanup_error"]
    assert (worktree_root / "unexpected-root-file.txt").exists()


@pytest.mark.asyncio
async def test_completion_finalization_merges_then_automatically_cleans_worktree_and_branch(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    codex_provider,
    app_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.models.conversation import Conversation
    from backend.models.task import AgentTask
    from backend.services.project_service import project_service
    from backend.services.task_service import task_service

    monkeypatch.setattr(task_service, "enqueue_task", lambda task: None)
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Automatic Completion Cleanup"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    await codex_provider(project["id"])
    repo = project["repos"][0]
    main_repo = project_service.repo_root(project["id"], repo["name"])
    run_git(main_repo, "branch", "dev")
    update = await client.put(
        f"/api/v2/projects/{project['id']}/repos/{repo['site_id']}/main-branch",
        json={"main_branch": "dev"},
        headers=auth_headers,
    )
    assert update.status_code == 200, update.text

    response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "自动清理完成会话", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = response.json()["conversation"]
    worktree_root = Path(conversation["worktree_root"])
    worktree_repo = worktree_root / repo["name"]
    branch_name = conversation["branch_name"]
    (worktree_repo / "automatic-cleanup.txt").write_text("merged and cleaned\n", encoding="utf-8")
    run_git(worktree_repo, "add", "automatic-cleanup.txt")
    run_git(worktree_repo, "commit", "-m", "Add automatic cleanup change")

    complete = await client.post(
        f"/api/v2/conversations/{conversation['id']}/complete",
        headers=auth_headers,
    )
    assert complete.status_code == 200, complete.text
    completion_task_id = complete.json()["task_id"]
    run_git(main_repo, "switch", "dev")
    run_git(main_repo, "merge", "--no-ff", branch_name, "-m", "Merge automatic cleanup conversation")

    async with app_module.AsyncSessionLocal() as db:
        task = await db.get(AgentTask, completion_task_id)
        cleanup = await task_service._mark_conversation_completed(db, task)
        conv = await db.get(Conversation, conversation["id"])
        assert conv.completion_status == "completed"
        assert conv.cleanup_status == "cleaned"
        assert cleanup["status"] == "cleaned"

    assert not worktree_root.exists()
    branch = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=str(main_repo),
        check=False,
    )
    assert branch.returncode != 0
    state_response = await client.get(
        f"/api/v2/conversations/{conversation['id']}/git",
        headers=auth_headers,
    )
    state = state_response.json()["git"]
    assert state["available"] is True
    assert state["live_available"] is False
    assert state["read_only"] is True
    assert "automatic-cleanup.txt" in state["repositories"][0]["diff"]

    archived = await client.delete(
        f"/api/v2/conversations/{conversation['id']}",
        headers=auth_headers,
    )
    assert archived.status_code == 200, archived.text
    archived_conversation = archived.json()["conversation"]
    assert archived_conversation["status"] == "archived"
    assert archived_conversation["completion_status"] == "completed"
    assert archived_conversation["cleanup_status"] == "cleaned"


@pytest.mark.asyncio
async def test_completion_rejects_dirty_or_untracked_worktree(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    codex_provider,
) -> None:
    create = await client.post(
        "/api/v2/projects",
        json={"name": "Dirty Completion Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    await codex_provider(project["id"])
    repo = project["repos"][0]
    response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "拒绝脏 worktree", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = response.json()["conversation"]
    (Path(conversation["worktree_root"]) / repo["name"] / "untracked.txt").write_text(
        "not committed\n",
        encoding="utf-8",
    )

    complete = await client.post(
        f"/api/v2/conversations/{conversation['id']}/complete",
        headers=auth_headers,
    )

    assert complete.status_code == 409
    assert "未提交或未跟踪" in complete.json()["detail"]


@pytest.mark.asyncio
async def test_archive_rejects_when_any_repository_has_merged_changes(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    from backend.services.project_service import project_service

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Partial Merge Archive Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    second = await client.post(
        f"/api/v2/projects/{project['id']}/repos",
        json={"name": "api"},
        headers=auth_headers,
    )
    assert second.status_code == 200, second.text
    refreshed = await client.get(f"/api/v2/projects/{project['id']}", headers=auth_headers)
    repos = refreshed.json()["project"]["repos"]
    conversation_response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={
            "title": "部分合并后禁止归档",
            "repo_ids": [repo["site_id"] for repo in repos],
            "provider": "codex",
        },
        headers=auth_headers,
    )
    conversation = conversation_response.json()["conversation"]
    first_repo = repos[0]
    worktree_repo = Path(conversation["worktree_root"]) / first_repo["name"]
    (worktree_repo / "merged-only-in-first.txt").write_text("merged\n", encoding="utf-8")
    run_git(worktree_repo, "add", "merged-only-in-first.txt")
    run_git(worktree_repo, "commit", "-m", "Change first repository")
    main_repo = project_service.repo_root(project["id"], first_repo["name"])
    run_git(main_repo, "merge", "--no-ff", conversation["branch_name"], "-m", "Merge first repository")

    archived = await client.delete(
        f"/api/v2/conversations/{conversation['id']}",
        headers=auth_headers,
    )

    assert archived.status_code == 409
    assert "已有仓库合并" in archived.json()["detail"]


@pytest.mark.asyncio
async def test_archive_cancels_tasks_linked_by_conversation_id(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    from backend.models.conversation import Conversation
    from backend.models.task import AgentTask

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Archive Running Task Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "取消运行任务", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = response.json()["conversation"]
    async with app_module.AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conversation["id"])
        task = AgentTask(
            id="archive-running-task",
            site_id=conv.site_id,
            project_id=conv.project_id,
            conversation_id=conv.id,
            provider="",
            task_type="develop_code",
            status="running",
        )
        db.add(task)
        await db.commit()

    archived = await client.delete(
        f"/api/v2/conversations/{conversation['id']}",
        headers=auth_headers,
    )

    assert archived.status_code == 200, archived.text
    async with app_module.AsyncSessionLocal() as db:
        task = await db.get(AgentTask, "archive-running-task")
        assert task.status == "canceled"


@pytest.mark.asyncio
async def test_archive_strict_path_validation_preserves_external_path(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
    tmp_path: Path,
) -> None:
    from backend.models.conversation import Conversation

    create = await client.post(
        "/api/v2/projects",
        json={"name": "Strict Cleanup Path Project"},
        headers=auth_headers,
    )
    project = create.json()["project"]
    repo = project["repos"][0]
    response = await client.post(
        f"/api/v2/conversations/project/{project['id']}",
        json={"title": "路径校验", "repo_ids": [repo["site_id"]], "provider": "codex"},
        headers=auth_headers,
    )
    conversation = response.json()["conversation"]
    external = tmp_path / "must-not-delete"
    external.mkdir()
    marker = external / "marker.txt"
    marker.write_text("preserve\n", encoding="utf-8")
    async with app_module.AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conversation["id"])
        items = list(conv.git_repos_json or [])
        items[0] = {**items[0], "worktree_path": str(external)}
        conv.git_repos_json = items
        await db.commit()

    archived = await client.delete(
        f"/api/v2/conversations/{conversation['id']}",
        headers=auth_headers,
    )

    assert archived.status_code == 200, archived.text
    payload = archived.json()["conversation"]
    assert payload["cleanup_status"] == "warning"
    assert "路径不安全" in payload["cleanup_error"]
    assert marker.read_text(encoding="utf-8") == "preserve\n"
