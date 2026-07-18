from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Remote Git Test",
    "GIT_AUTHOR_EMAIL": "remote-git@example.com",
    "GIT_COMMITTER_NAME": "Remote Git Test",
    "GIT_COMMITTER_EMAIL": "remote-git@example.com",
}


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=check,
        env=GIT_ENV,
    )


def create_remote_worktree(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict[str, str]]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    repo = tmp_path / "repo"
    peer = tmp_path / "peer"
    worktree = tmp_path / "worktree"
    remote.mkdir()
    git(remote, "init", "--bare")
    seed.mkdir()
    git(seed, "init")
    git(seed, "switch", "-c", "dev")
    (seed / "base.txt").write_text("base\n", encoding="utf-8")
    git(seed, "add", "base.txt")
    git(seed, "commit", "-m", "Initial")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "dev")
    git(tmp_path, "clone", "--branch", "dev", str(remote), str(repo))
    git(tmp_path, "clone", "--branch", "dev", str(remote), str(peer))
    git(repo, "worktree", "add", "-b", "codex/remote-completion", str(worktree), "dev")
    item = {
        "site_id": "site-public",
        "site_db_id": "site-db",
        "name": "repo",
        "repo_path": str(repo),
        "worktree_path": str(worktree),
        "main_branch": "dev",
        "branch_name": "codex/remote-completion",
    }
    return remote, repo, peer, worktree, item


def commit_file(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def test_completion_fetches_remote_rebases_task_and_pushes_verified_main(tmp_path: Path) -> None:
    from backend.services.conversation_git_service import conversation_git_service

    remote, repo, peer, worktree, item = create_remote_worktree(tmp_path)
    remote_sha = commit_file(peer, "remote.txt", "remote latest\n", "Remote update")
    git(peer, "push", "origin", "dev")
    commit_file(worktree, "task.txt", "task change\n", "Task update")

    prepared = conversation_git_service.prepare_repositories_for_completion([item])

    assert prepared[0]["remote_status"] == "synchronized"
    assert prepared[0]["push_status"] == "pending"
    assert prepared[0]["remote_before_sha"] == remote_sha
    assert (repo / "remote.txt").read_text(encoding="utf-8") == "remote latest\n"
    assert (worktree / "remote.txt").read_text(encoding="utf-8") == "remote latest\n"
    assert (worktree / "task.txt").read_text(encoding="utf-8") == "task change\n"

    git(repo, "merge", "--no-ff", prepared[0]["branch_name"], "-m", "Merge task")
    verified = conversation_git_service.verify_completed_repositories(prepared)
    pushed = conversation_git_service.push_completed_repositories(verified)

    local_sha = git(repo, "rev-parse", "dev").stdout.strip()
    remote_after = git(remote, "rev-parse", "refs/heads/dev").stdout.strip()
    assert pushed[0]["push_status"] == "pushed"
    assert pushed[0]["remote_status"] == "verified"
    assert pushed[0]["remote_after_sha"] == local_sha == remote_after


def test_completion_rebase_conflict_is_aborted_and_retryable(tmp_path: Path) -> None:
    from backend.services.conversation_git_service import conversation_git_service

    _, _, peer, worktree, item = create_remote_worktree(tmp_path)
    commit_file(worktree, "base.txt", "task version\n", "Task conflict")
    commit_file(peer, "base.txt", "remote version\n", "Remote conflict")
    git(peer, "push", "origin", "dev")
    task_before = git(worktree, "rev-parse", "HEAD").stdout.strip()

    with pytest.raises(RuntimeError, match="rebase 冲突或失败，已安全中止"):
        conversation_git_service.prepare_repositories_for_completion([item])

    assert git(worktree, "rev-parse", "HEAD").stdout.strip() == task_before
    assert git(worktree, "status", "--porcelain").stdout.strip() == ""
    git_dir = Path(git(worktree, "rev-parse", "--git-dir").stdout.strip())
    if not git_dir.is_absolute():
        git_dir = worktree / git_dir
    assert not (git_dir / "rebase-merge").exists()
    assert not (git_dir / "rebase-apply").exists()


def test_completion_rejects_non_fast_forward_push_after_remote_race(tmp_path: Path) -> None:
    from backend.services.conversation_git_service import conversation_git_service

    remote, repo, peer, worktree, item = create_remote_worktree(tmp_path)
    commit_file(worktree, "task.txt", "task change\n", "Task update")
    prepared = conversation_git_service.prepare_repositories_for_completion([item])
    git(repo, "merge", "--no-ff", prepared[0]["branch_name"], "-m", "Merge task")
    verified = conversation_git_service.verify_completed_repositories(prepared)

    commit_file(peer, "race.txt", "remote race\n", "Remote race")
    git(peer, "push", "origin", "dev")
    remote_race_sha = git(remote, "rev-parse", "refs/heads/dev").stdout.strip()

    with pytest.raises(RuntimeError, match="不是 fast-forward"):
        conversation_git_service.push_completed_repositories(verified)

    assert verified[0]["push_status"] == "failed"
    assert git(remote, "rev-parse", "refs/heads/dev").stdout.strip() == remote_race_sha


def test_completion_without_origin_is_explicitly_marked_as_local_only(tmp_path: Path) -> None:
    from backend.services.conversation_git_service import conversation_git_service

    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repo.mkdir()
    git(repo, "init")
    git(repo, "switch", "-c", "dev")
    commit_file(repo, "base.txt", "base\n", "Initial")
    git(repo, "worktree", "add", "-b", "codex/local", str(worktree), "dev")
    item = {
        "name": "repo",
        "repo_path": str(repo),
        "worktree_path": str(worktree),
        "main_branch": "dev",
        "branch_name": "codex/local",
    }

    prepared = conversation_git_service.prepare_repositories_for_completion([item])

    assert prepared[0]["remote_status"] == "not_configured"
    assert prepared[0]["push_status"] == "skipped"
    assert "仅完成本地合并" in prepared[0]["remote_error"]


def test_existing_origin_credentials_are_cleaned_without_entering_git_arguments(tmp_path: Path) -> None:
    from backend.services.conversation_git_service import conversation_git_service

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "remote", "add", "origin", "https://user:super-secret@example.invalid/repo.git")

    public_url, auth = conversation_git_service._origin_auth(repo, {})

    assert public_url == "https://example.invalid/repo.git"
    assert auth == {"username": "user", "password": "super-secret"}
    assert git(repo, "remote", "get-url", "origin").stdout.strip() == public_url

