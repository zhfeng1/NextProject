from __future__ import annotations

import asyncio
import os
import re
import subprocess
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from fastapi import HTTPException
import redis.asyncio as aioredis
from redis.exceptions import RedisError

from backend.core.config import get_settings
from backend.models.repo_git_operation import RepoGitOperation


COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
MAX_GRAPH_LIMIT = 500


class GitHistoryService:
    _memory_locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _git_env() -> dict[str, str]:
        return {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
        }

    def _run_git(
        self,
        repo: Path,
        args: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=self._git_env(),
            timeout=20,
        )
        if check and result.returncode != 0:
            # These operations never contact a remote, so stderr cannot contain credentials.
            message = (result.stderr or result.stdout or "Git operation failed").strip()
            raise RuntimeError(message[:2000])
        return result

    def ensure_repository_path(
        self,
        expected: Path,
        supplied: str | Path | None = None,
        *,
        boundary: Path | None = None,
    ) -> Path:
        expected_path = expected.resolve(strict=False)
        actual = Path(supplied).resolve(strict=False) if supplied else expected_path
        if actual != expected_path:
            raise HTTPException(status_code=409, detail="仓库路径与项目元数据不一致")
        if boundary is not None and not actual.is_relative_to(boundary.resolve(strict=False)):
            raise HTTPException(status_code=409, detail="仓库路径超出项目边界")
        if not actual.exists():
            raise HTTPException(status_code=409, detail="仓库尚未准备完成")
        result = self._run_git(actual, ["rev-parse", "--is-inside-work-tree"], check=False)
        if result.returncode != 0:
            raise HTTPException(status_code=409, detail="目录不是 Git 仓库")
        return actual

    def ensure_worktree_path(
        self,
        expected: Path,
        supplied: str | Path,
        *,
        boundary: Path | None = None,
    ) -> Path:
        expected_path = expected.resolve(strict=False)
        actual = Path(supplied).resolve(strict=False)
        if actual != expected_path:
            raise HTTPException(status_code=409, detail="会话 worktree 路径与会话元数据不一致")
        if boundary is not None and not actual.is_relative_to(boundary.resolve(strict=False)):
            raise HTTPException(status_code=409, detail="会话 worktree 路径超出项目边界")
        if not actual.exists():
            raise HTTPException(status_code=409, detail="会话 worktree 已不存在")
        return actual

    def _verify_branch(self, repo: Path, branch: str) -> str:
        if not branch:
            raise HTTPException(status_code=409, detail="分支元数据不完整")
        valid = self._run_git(repo, ["check-ref-format", "--branch", branch], check=False)
        if valid.returncode != 0:
            raise HTTPException(status_code=409, detail="分支名称不合法")
        full_ref = f"refs/heads/{branch}"
        exists = self._run_git(repo, ["show-ref", "--verify", "--quiet", full_ref], check=False)
        if exists.returncode != 0:
            raise HTTPException(status_code=409, detail=f"本地分支已不存在: {branch}")
        return full_ref

    def local_branch_exists(self, repo: Path, branch: str) -> bool:
        if not branch:
            return False
        valid = self._run_git(repo, ["check-ref-format", "--branch", branch], check=False)
        if valid.returncode != 0:
            return False
        return self._run_git(
            repo,
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            check=False,
        ).returncode == 0

    def _resolve_commit(self, repo: Path, revision: str) -> str:
        result = self._run_git(repo, ["rev-parse", "--verify", f"{revision}^{{commit}}"], check=False)
        if result.returncode != 0 or not COMMIT_SHA_PATTERN.fullmatch(result.stdout.strip()):
            raise HTTPException(status_code=404, detail="Commit 不存在")
        return result.stdout.strip().lower()

    @staticmethod
    def _label(ref_name: str, current_branch: str, sha: str) -> dict[str, Any] | None:
        if ref_name.startswith("refs/heads/"):
            name = ref_name.removeprefix("refs/heads/")
            ref_type = "local_branch"
        elif ref_name.startswith("refs/remotes/"):
            name = ref_name.removeprefix("refs/remotes/")
            ref_type = "remote_branch"
        elif ref_name.startswith("refs/tags/"):
            name = ref_name.removeprefix("refs/tags/")
            ref_type = "tag"
        else:
            return None
        return {
            "name": name,
            "full_name": ref_name,
            "type": ref_type,
            "current": ref_name == f"refs/heads/{current_branch}",
            "sha": sha,
        }

    def _refs(self, repo: Path, current_branch: str) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        result = self._run_git(
            repo,
            [
                "for-each-ref",
                "--format=%(objectname)%00%(*objectname)%00%(refname)",
                "refs/heads",
                "refs/remotes",
                "refs/tags",
            ],
            check=False,
        )
        by_sha: dict[str, list[dict[str, Any]]] = {}
        branches: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            parts = line.split("\0")
            if len(parts) != 3:
                continue
            object_sha, peeled_sha, ref_name = (part.strip() for part in parts)
            sha = (peeled_sha or object_sha).lower()
            if not COMMIT_SHA_PATTERN.fullmatch(sha):
                continue
            label = self._label(ref_name, current_branch, sha)
            if label is None:
                continue
            by_sha.setdefault(sha, []).append({key: value for key, value in label.items() if key != "sha"})
            branches.append(label)
        branches.sort(key=lambda item: (not item["current"], item["type"], item["name"]))
        return by_sha, branches

    @staticmethod
    def _assign_lanes(commits: list[dict[str, Any]]) -> int:
        active: list[str] = []
        max_lanes = 1 if commits else 0
        for commit in commits:
            sha = str(commit["sha"])
            if sha not in active:
                active.append(sha)
            lane = active.index(sha)
            commit["lane"] = lane

            parents = [str(parent) for parent in commit.get("parents") or []]
            active[lane:lane + 1] = parents
            deduplicated: list[str] = []
            for item in active:
                if item not in deduplicated:
                    deduplicated.append(item)
            active = deduplicated
            commit["parent_lanes"] = [
                {"sha": parent, "lane": active.index(parent)}
                for parent in parents
                if parent in active
            ]
            max_lanes = max(max_lanes, lane + 1, len(active))
        return max_lanes

    @staticmethod
    def _unique_revisions(revisions: Iterable[str]) -> list[str]:
        result: list[str] = []
        for revision in revisions:
            if revision and revision not in result:
                result.append(revision)
        return result

    def graph(
        self,
        *,
        repo: Path,
        site_id: str,
        name: str,
        branch: str,
        default_branch: str,
        scope: str,
        revisions: list[str] | None = None,
        head_revision: str = "",
        limit: int = 200,
        skip: int = 0,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), MAX_GRAPH_LIMIT))
        skip = max(0, int(skip))
        selected_ref = self._verify_branch(repo, branch) if not head_revision else head_revision
        head_sha = self._resolve_commit(repo, selected_ref)

        resolved_revisions: list[str] = []
        for revision in self._unique_revisions(revisions or [selected_ref]):
            if COMMIT_SHA_PATTERN.fullmatch(revision):
                resolved_revisions.append(self._resolve_commit(repo, revision))
            elif revision.startswith(("refs/heads/", "refs/remotes/", "refs/tags/")):
                exists = self._run_git(repo, ["show-ref", "--verify", "--quiet", revision], check=False)
                if exists.returncode == 0:
                    resolved_revisions.append(revision)
            else:
                valid = self._run_git(repo, ["check-ref-format", "--branch", revision], check=False)
                if valid.returncode != 0:
                    raise HTTPException(status_code=409, detail="图谱分支名称不合法")
                full_ref = f"refs/heads/{revision}"
                if self._run_git(repo, ["show-ref", "--verify", "--quiet", full_ref], check=False).returncode == 0:
                    resolved_revisions.append(full_ref)
        if head_sha not in resolved_revisions and selected_ref not in resolved_revisions:
            resolved_revisions.append(head_sha)

        count_result = self._run_git(repo, ["rev-list", "--count", *resolved_revisions])
        total = int(count_result.stdout.strip() or "0")
        fetch_count = min(total, skip + limit)
        format_value = "%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%cI%x1f%s%x1f%B%x1e"
        log_result = self._run_git(
            repo,
            [
                "log",
                "--topo-order",
                "--date-order",
                f"--max-count={fetch_count}",
                f"--format={format_value}",
                *resolved_revisions,
            ],
        )
        labels_by_sha, branches = self._refs(repo, branch)
        commits: list[dict[str, Any]] = []
        for record in log_result.stdout.split("\x1e"):
            fields = record.strip("\n").split("\x1f", 7)
            if len(fields) != 8:
                continue
            sha, parents, author_name, author_email, authored_at, committed_at, subject, message = fields
            sha = sha.strip().lower()
            if not COMMIT_SHA_PATTERN.fullmatch(sha):
                continue
            commits.append({
                "sha": sha,
                "short_sha": sha[:8],
                "subject": subject.strip(),
                "message": message.strip(),
                "author_name": author_name.strip(),
                "author_email": author_email.strip(),
                "authored_at": authored_at.strip(),
                "committed_at": committed_at.strip(),
                "parents": [item.lower() for item in parents.split() if COMMIT_SHA_PATTERN.fullmatch(item)],
                "labels": labels_by_sha.get(sha, []),
                "current": sha == head_sha,
            })
        lanes = self._assign_lanes(commits)
        visible_commits = commits[skip:skip + limit]
        return {
            "site_id": site_id,
            "name": name,
            "branch": branch,
            "default_branch": default_branch,
            "scope": scope,
            "head_sha": head_sha,
            "total": total,
            "skip": skip,
            "limit": limit,
            "truncated": skip + len(visible_commits) < total,
            "commits": visible_commits,
            "branches": branches,
            "lanes": lanes,
        }

    def rollback_branch(
        self,
        *,
        repo: Path,
        branch: str,
        target_sha: str,
        expected_worktree: Path | None,
    ) -> tuple[str, str]:
        if not COMMIT_SHA_PATTERN.fullmatch(target_sha or ""):
            raise HTTPException(status_code=400, detail="commit_sha 必须是完整的 40 位 Commit SHA")
        full_ref = self._verify_branch(repo, branch)
        before_sha = self._resolve_commit(repo, full_ref)
        target = self._resolve_commit(repo, target_sha.lower())
        ancestor = self._run_git(repo, ["merge-base", "--is-ancestor", target, before_sha], check=False)
        if ancestor.returncode != 0:
            raise HTTPException(status_code=409, detail="只能回滚到当前分支历史中的 Commit")

        worktree_result = self._run_git(repo, ["worktree", "list", "--porcelain"], check=False)
        checked_out_path: Path | None = None
        current_path: Path | None = None
        for line in worktree_result.stdout.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                current_path = Path(value.strip()).resolve(strict=False)
            elif key == "branch" and value.strip() == full_ref:
                checked_out_path = current_path
                break

        if expected_worktree is not None:
            expected = expected_worktree.resolve(strict=False)
            if checked_out_path != expected:
                raise HTTPException(status_code=409, detail="目标分支与会话 worktree 不匹配")
        if checked_out_path is not None:
            dirty = self._run_git(
                checked_out_path,
                ["status", "--porcelain", "--untracked-files=normal"],
                check=False,
            ).stdout.strip()
            if dirty:
                raise HTTPException(status_code=409, detail="目标分支存在未提交或未跟踪修改，不能回滚")
            self._run_git(checked_out_path, ["reset", "--hard", target])
        else:
            self._run_git(repo, ["update-ref", full_ref, target, before_sha])

        after_sha = self._resolve_commit(repo, full_ref)
        if after_sha != target:
            raise RuntimeError("回滚后分支指针校验失败")
        return before_sha, after_sha

    @asynccontextmanager
    async def repository_lock(
        self,
        lock_name: str,
        *,
        busy_message: str = "仓库正在执行其他 Git 操作，请稍后重试",
    ) -> AsyncIterator[None]:
        settings = get_settings()
        if settings.auth_session_backend == "memory":
            lock = self._memory_locks.setdefault(lock_name, asyncio.Lock())
            try:
                await asyncio.wait_for(lock.acquire(), timeout=5)
            except asyncio.TimeoutError as exc:
                raise HTTPException(status_code=409, detail=busy_message) from exc
            try:
                yield
            finally:
                lock.release()
            return

        client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        key = f"nextproject:site-lock:{lock_name}"
        token = f"git-rollback:{uuid.uuid4()}"
        release_script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        try:
            acquired = await client.set(key, token, nx=True, ex=300)
            if not acquired:
                raise HTTPException(status_code=409, detail=busy_message)
            yield
        except RedisError as exc:
            raise HTTPException(status_code=503, detail="Git 操作锁服务不可用") from exc
        finally:
            try:
                await client.eval(release_script, 1, key, token)
            except RedisError:
                pass
            await client.aclose()

    @asynccontextmanager
    async def project_lock(self, project_id: str) -> AsyncIterator[None]:
        async with self.repository_lock(
            f"project:{project_id}",
            busy_message="项目正在执行任务或其他 Git 操作，请稍后重试",
        ):
            yield

    @staticmethod
    def serialize_operation(operation: RepoGitOperation) -> dict[str, Any]:
        return {
            "id": str(operation.id),
            "scope": operation.scope,
            "operation": operation.operation,
            "project_id": str(operation.project_id),
            "site_id": operation.site_id,
            "conversation_id": str(operation.conversation_id or ""),
            "repo_name": operation.repo_name,
            "branch": operation.branch,
            "target_sha": operation.target_sha,
            "before_sha": operation.before_sha,
            "after_sha": operation.after_sha,
            "status": operation.status,
            "error": operation.error,
            "created_at": operation.created_at.isoformat() if operation.created_at else None,
            "updated_at": operation.updated_at.isoformat() if operation.updated_at else None,
        }


git_history_service = GitHistoryService()
