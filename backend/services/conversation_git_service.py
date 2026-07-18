from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit, urlunsplit

from fastapi import HTTPException

from backend.models.site import Site
from backend.services.execution_trace_service import redact_execution_text
from backend.services.programming_tool_service import programming_tool_service
from backend.services.project_service import project_service


DIFF_MAX_BYTES = 256_000
FILE_DIFF_MAX_BYTES = 2_000_000
BRANCH_MAX_LENGTH = 180


class ConversationGitService:
    @staticmethod
    def _git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "NextProject",
            "GIT_AUTHOR_EMAIL": "bot@nextproject",
            "GIT_COMMITTER_NAME": "NextProject",
            "GIT_COMMITTER_EMAIL": "bot@nextproject",
        }
        if extra:
            env.update(extra)
        return env

    @staticmethod
    def _safe_git_error(value: str) -> str:
        return redact_execution_text(value or "git command failed")

    def _run_git(
        self,
        repo: Path,
        args: list[str],
        *,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=self._git_env(env),
        )
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "git command failed").strip()
            raise RuntimeError(self._safe_git_error(message))
        return result

    @staticmethod
    def _strip_url_credentials(value: str) -> str:
        url = str(value or "").strip()
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return url
        netloc = parts.hostname
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    @staticmethod
    def _credentials_from_url(value: str) -> tuple[str, str]:
        parts = urlsplit(str(value or ""))
        if parts.scheme not in {"http", "https"}:
            return "", ""
        return unquote(parts.username or ""), unquote(parts.password or "")

    @contextmanager
    def _git_network_env(self, auth: dict[str, str] | None) -> Iterator[dict[str, str]]:
        auth = auth or {}
        username = str(auth.get("username") or "")
        password = str(auth.get("password") or "")
        with tempfile.TemporaryDirectory(prefix="nextproject-git-auth-") as temp_dir:
            askpass = Path(temp_dir) / "askpass.sh"
            askpass.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  *Username*) printf '%s\\n' \"$NEXT_PROJECT_GIT_USERNAME\" ;;\n"
                "  *Password*) printf '%s\\n' \"$NEXT_PROJECT_GIT_PASSWORD\" ;;\n"
                "  *) printf '\\n' ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            yield {
                "GIT_ASKPASS": str(askpass),
                "GIT_ASKPASS_REQUIRE": "force",
                "GIT_TERMINAL_PROMPT": "0",
                "NEXT_PROJECT_GIT_USERNAME": username,
                "NEXT_PROJECT_GIT_PASSWORD": password,
            }

    def _origin_auth(
        self,
        repo: Path,
        configured: dict[str, str] | None,
    ) -> tuple[str, dict[str, str]]:
        configured = configured or {}
        current = self._run_git(repo, ["remote", "get-url", "origin"], check=False)
        if current.returncode != 0 or not current.stdout.strip():
            raise RuntimeError(f"仓库 {repo.name} 未配置 origin 远端，无法完成并推送")
        current_url = current.stdout.strip()
        embedded_username, embedded_password = self._credentials_from_url(current_url)
        configured_url = str(configured.get("remote_url") or "").strip()
        public_url = self._strip_url_credentials(configured_url or current_url)
        if not public_url:
            raise RuntimeError(f"仓库 {repo.name} 的 origin 远端地址无效")
        if current_url != public_url:
            changed = self._run_git(repo, ["remote", "set-url", "origin", public_url], check=False)
            if changed.returncode != 0:
                error = changed.stderr or changed.stdout or "无法更新 origin 远端地址"
                raise RuntimeError(self._safe_git_error(error))
        return public_url, {
            "username": str(configured.get("username") or embedded_username or ""),
            "password": str(configured.get("password") or embedded_password or ""),
        }

    def _fetch_remote_main(
        self,
        repo: Path,
        main_branch: str,
        auth: dict[str, str] | None,
    ) -> tuple[str, dict[str, str]]:
        _, resolved_auth = self._origin_auth(repo, auth)
        with self._git_network_env(resolved_auth) as network_env:
            fetched = self._run_git(
                repo,
                [
                    "-c",
                    "credential.helper=",
                    "fetch",
                    "--no-tags",
                    "origin",
                    f"+refs/heads/{main_branch}:refs/remotes/origin/{main_branch}",
                ],
                check=False,
                env=network_env,
            )
        if fetched.returncode != 0:
            error = fetched.stderr or fetched.stdout or "git fetch failed"
            raise RuntimeError(f"获取远端主分支失败: {self._safe_git_error(error)}")
        remote_revision = f"refs/remotes/origin/{main_branch}"
        try:
            remote_sha = self._rev_parse(repo, remote_revision)
        except RuntimeError as exc:
            raise RuntimeError(f"远端不存在主分支 origin/{main_branch}") from exc
        return remote_sha, resolved_auth

    def _rebase_in_progress(self, repo: Path) -> bool:
        for name in ("rebase-merge", "rebase-apply"):
            path = self._run_git(repo, ["rev-parse", "--git-path", name], check=False)
            if path.returncode == 0 and path.stdout.strip():
                candidate = Path(path.stdout.strip())
                if not candidate.is_absolute():
                    candidate = repo / candidate
                if candidate.exists():
                    return True
        return False

    def _rebase_branch(self, repo: Path, upstream: str, label: str) -> None:
        if self._rebase_in_progress(repo):
            raise RuntimeError(f"仓库 {repo.name} 已有未完成的 rebase，请先处理后重试")
        result = self._run_git(repo, ["rebase", upstream], check=False)
        if result.returncode == 0:
            return
        error = self._safe_git_error(result.stderr or result.stdout or "git rebase failed")
        if self._rebase_in_progress(repo):
            self._run_git(repo, ["rebase", "--abort"], check=False)
        raise RuntimeError(f"{label} rebase 冲突或失败，已安全中止: {error}")

    def _ensure_repo(self, repo: Path) -> None:
        if not repo.exists():
            raise HTTPException(status_code=409, detail=f"仓库尚未准备完成: {repo.name}")
        result = self._run_git(repo, ["rev-parse", "--is-inside-work-tree"], check=False)
        if result.returncode != 0:
            raise HTTPException(status_code=409, detail=f"目录不是 Git 仓库: {repo.name}")
        head = self._run_git(repo, ["rev-parse", "HEAD"], check=False)
        if head.returncode != 0:
            self._run_git(repo, ["add", "-A"])
            self._run_git(repo, ["commit", "--allow-empty", "-m", "NextProject initial checkpoint"])

    def _branch_exists(self, repo: Path, branch: str) -> bool:
        local = self._run_git(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
        if local.returncode == 0:
            return True
        remote = self._run_git(repo, ["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], check=False)
        return remote.returncode == 0

    def _local_branch_exists(self, repo: Path, branch: str) -> bool:
        result = self._run_git(
            repo,
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            check=False,
        )
        return result.returncode == 0

    def _worktree_entries(self, repo: Path) -> list[dict[str, str]]:
        result = self._run_git(repo, ["worktree", "list", "--porcelain"], check=False)
        entries: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if not line:
                if current:
                    entries.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            if key in {"worktree", "HEAD", "branch"}:
                current[key] = value.strip()
        if current:
            entries.append(current)
        return entries

    def _rev_parse(self, repo: Path, revision: str) -> str:
        result = self._run_git(repo, ["rev-parse", "--verify", revision], check=False)
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"无法解析 Git revision: {revision}")
        return result.stdout.strip()

    def capture_repository_tips(
        self,
        git_repos: list[dict[str, Any]],
        *,
        require_clean: bool,
    ) -> list[dict[str, Any]]:
        updated: list[dict[str, Any]] = []
        for original in git_repos:
            item = dict(original)
            repo = Path(str(item.get("repo_path") or ""))
            worktree = Path(str(item.get("worktree_path") or ""))
            name = str(item.get("name") or item.get("site_id") or "仓库")
            main_branch = str(item.get("main_branch") or "").strip()
            branch_name = str(item.get("branch_name") or "").strip()
            self._ensure_repo(repo)
            if require_clean:
                if not worktree.exists():
                    raise RuntimeError(f"仓库 {name} 的会话 worktree 不存在")
                dirty = self._run_git(worktree, ["status", "--porcelain"], check=False).stdout.strip()
                if dirty:
                    raise RuntimeError(f"仓库 {name} 的会话 worktree 有未提交或未跟踪修改")
            item["main_before_sha"] = self._rev_parse(repo, main_branch)
            item["branch_tip_sha"] = self._rev_parse(repo, branch_name)
            updated.append(item)
        return updated

    def verify_completed_repositories(self, git_repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        updated: list[dict[str, Any]] = []
        for original in git_repos:
            item = dict(original)
            repo = Path(str(item.get("repo_path") or ""))
            worktree = Path(str(item.get("worktree_path") or ""))
            name = str(item.get("name") or item.get("site_id") or "仓库")
            main_branch = str(item.get("main_branch") or "").strip()
            branch_tip = str(item.get("branch_tip_sha") or "").strip()
            if not branch_tip:
                branch_name = str(item.get("branch_name") or "").strip()
                branch_tip = self._rev_parse(repo, branch_name)
                item["branch_tip_sha"] = branch_tip
                item.setdefault("main_before_sha", self._rev_parse(repo, main_branch))
            if worktree.exists():
                dirty = self._run_git(worktree, ["status", "--porcelain"], check=False).stdout.strip()
                if dirty:
                    raise RuntimeError(f"仓库 {name} 的会话 worktree 仍有未提交或未跟踪修改")
            merged = self._run_git(
                repo,
                ["merge-base", "--is-ancestor", branch_tip, main_branch],
                check=False,
            )
            if merged.returncode != 0:
                raise RuntimeError(f"仓库 {name} 的任务分支尚未完整合并")
            item["main_after_sha"] = self._rev_parse(repo, main_branch)
            item["merge_status"] = "merged"
            updated.append(item)
        return updated

    def has_merged_changes(self, item: dict[str, Any]) -> bool:
        repo = Path(str(item.get("repo_path") or ""))
        branch_name = str(item.get("branch_name") or "")
        main_branch = str(item.get("main_branch") or "")
        branch_tip = self._rev_parse(repo, branch_name)
        merged = self._run_git(
            repo,
            ["merge-base", "--is-ancestor", branch_tip, main_branch],
            check=False,
        )
        if merged.returncode != 0:
            return False
        baseline = str(item.get("main_before_sha") or "").strip()
        if not baseline:
            baseline = self._rev_parse(repo, main_branch)
        return branch_tip != baseline

    def _ensure_local_branch(self, repo: Path, branch: str) -> bool:
        local = self._run_git(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
        if local.returncode == 0:
            return True
        remote = self._run_git(
            repo,
            ["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
            check=False,
        )
        if remote.returncode != 0:
            return False
        self._run_git(repo, ["branch", branch, f"origin/{branch}"])
        return True

    def resolve_main_branch(self, site: Site, repo: Path) -> str:
        self._ensure_repo(repo)
        configured = str(getattr(site, "main_branch", "") or "").strip()
        config = getattr(site, "config", {}) or {}
        git_source = config.get("git_source") if isinstance(config, dict) else {}
        cloned_branch = str((git_source or {}).get("branch") or "").strip()

        if configured:
            if not self._ensure_local_branch(repo, configured):
                raise HTTPException(status_code=409, detail=f"仓库 {site.name} 不存在主分支 {configured}")
            return configured

        candidates: list[str] = []
        if cloned_branch:
            candidates.append(cloned_branch)
        remote_head = self._run_git(repo, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], check=False)
        if remote_head.returncode == 0 and remote_head.stdout.strip().startswith("origin/"):
            candidates.append(remote_head.stdout.strip().removeprefix("origin/"))
        current = self._run_git(repo, ["branch", "--show-current"], check=False).stdout.strip()
        if current:
            candidates.append(current)
        candidates.extend(["main", "master", "dev"])

        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            if self._ensure_local_branch(repo, candidate):
                return candidate
        raise HTTPException(status_code=409, detail=f"无法识别仓库 {site.name} 的主分支，请先在项目页面设置")

    def set_main_branch(self, site: Site, repo: Path, branch: str) -> str:
        normalized = branch.strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="主分支不能为空")
        valid = self._run_git(repo, ["check-ref-format", "--branch", normalized], check=False)
        if valid.returncode != 0:
            raise HTTPException(status_code=400, detail="主分支名称不合法")
        self._ensure_repo(repo)
        if not self._ensure_local_branch(repo, normalized):
            raise HTTPException(status_code=404, detail=f"分支不存在: {normalized}")
        return normalized

    @staticmethod
    def _provider_prefix(provider: str) -> str:
        spec = programming_tool_service.get_spec((provider or "").strip().lower())
        return spec.branch_prefix.rstrip("/") if spec else "agent"

    @staticmethod
    def _task_slug(title: str, fallback: str) -> str:
        first_line = next((line.strip() for line in (title or "").splitlines() if line.strip()), "")
        value = first_line or fallback
        value = re.sub(r"[\x00-\x20~^:?*\[\]\\/]+", "-", value)
        value = value.replace("@{", "-")
        value = re.sub(r"\.{2,}", "-", value)
        value = re.sub(r"-+", "-", value).strip("-./")
        if value.endswith(".lock"):
            value = value[:-5]
        return (value or fallback)[:96].rstrip("-./")

    def _branch_candidate(self, title: str, provider: str, fallback: str) -> str:
        prefix = self._provider_prefix(provider)
        slug = self._task_slug(title, fallback)
        return f"{prefix}/{slug}"[:BRANCH_MAX_LENGTH].rstrip("./")

    def _unique_branch(self, repos: list[Path], base: str, conversation_id: str, ignore: str = "") -> str:
        candidates = [base, f"{base}-{conversation_id[:8]}"]
        candidates.extend(f"{base}-{conversation_id[:8]}-{index}" for index in range(2, 100))
        for candidate in candidates:
            if all(candidate == ignore or not self._branch_exists(repo, candidate) for repo in repos):
                return candidate
        raise HTTPException(status_code=409, detail="无法生成唯一的会话分支名称")

    def create_worktrees(
        self,
        *,
        project_id: str,
        sites: list[Site],
        conversation_id: str,
        title: str,
        provider: str,
    ) -> tuple[Path, str, list[dict[str, Any]]]:
        project_root = project_service.project_root(project_id)
        worktree_root = project_root / ".worktree" / conversation_id
        repos = [project_service.repo_root(project_id, site.name) for site in sites]
        main_branches = [self.resolve_main_branch(site, repo) for site, repo in zip(sites, repos)]
        base = self._branch_candidate(title, provider, f"session-{conversation_id[:8]}")
        branch_name = self._unique_branch(repos, base, conversation_id)
        created: list[tuple[Path, Path]] = []
        metadata: list[dict[str, Any]] = []
        try:
            worktree_root.mkdir(parents=True, exist_ok=False)
            for site, repo, main_branch in zip(sites, repos, main_branches):
                current = self._run_git(repo, ["branch", "--show-current"], check=False).stdout.strip()
                dirty = bool(self._run_git(repo, ["status", "--porcelain"], check=False).stdout.strip())
                if dirty and current != main_branch:
                    raise HTTPException(
                        status_code=409,
                        detail=f"仓库 {site.name} 当前分支有未提交修改，请先处理后再创建会话",
                    )
                if dirty:
                    self._run_git(repo, ["add", "-A"])
                    self._run_git(repo, ["commit", "-m", "NextProject pre-session checkpoint"])
                self._run_git(repo, ["worktree", "prune"], check=False)
                worktree_path = worktree_root / site.name
                self._run_git(repo, ["worktree", "add", "-b", branch_name, str(worktree_path), main_branch])
                created.append((repo, worktree_path))
                metadata.append({
                    "site_id": site.site_id,
                    "site_db_id": str(site.id),
                    "name": site.name,
                    "repo_path": str(repo),
                    "worktree_path": str(worktree_path),
                    "main_branch": main_branch,
                    "branch_name": branch_name,
                    "main_before_sha": self._rev_parse(repo, main_branch),
                    "branch_tip_sha": self._rev_parse(repo, branch_name),
                })
        except Exception:
            for repo, worktree_path in reversed(created):
                self._run_git(repo, ["worktree", "remove", "--force", str(worktree_path)], check=False)
            shutil.rmtree(worktree_root, ignore_errors=True)
            raise
        return worktree_root, branch_name, metadata

    def rename_worktree_branch(
        self,
        *,
        git_repos: list[dict[str, Any]],
        conversation_id: str,
        title: str,
        provider: str,
        current_branch: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        repos = [Path(item["repo_path"]) for item in git_repos]
        base = self._branch_candidate(title, provider, f"session-{conversation_id[:8]}")
        branch_name = self._unique_branch(repos, base, conversation_id, ignore=current_branch)
        if branch_name == current_branch:
            return current_branch, git_repos
        renamed: list[Path] = []
        try:
            for item in git_repos:
                worktree = Path(item["worktree_path"])
                self._run_git(worktree, ["branch", "-m", branch_name])
                renamed.append(worktree)
        except Exception:
            for worktree in reversed(renamed):
                self._run_git(worktree, ["branch", "-m", current_branch], check=False)
            raise
        updated = [{**item, "branch_name": branch_name} for item in git_repos]
        return branch_name, updated

    def remove_worktrees(self, git_repos: list[dict[str, Any]], worktree_root: str = "") -> None:
        for item in reversed(git_repos):
            repo = Path(str(item.get("repo_path") or ""))
            worktree = Path(str(item.get("worktree_path") or ""))
            if repo.exists() and str(worktree):
                self._run_git(repo, ["worktree", "remove", "--force", str(worktree)], check=False)
        if worktree_root:
            shutil.rmtree(worktree_root, ignore_errors=True)

    def prepare_repositories_for_completion(
        self,
        git_repos: list[dict[str, Any]],
        *,
        remote_auth: dict[str, dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Synchronize main/task branches onto the latest remote main without rewriting remote history."""

        updated: list[dict[str, Any]] = []
        remote_auth = remote_auth or {}
        for original in git_repos:
            item = dict(original)
            repo = Path(str(item.get("repo_path") or ""))
            worktree = Path(str(item.get("worktree_path") or ""))
            name = str(item.get("name") or item.get("site_id") or "仓库")
            main_branch = str(item.get("main_branch") or "").strip()
            branch_name = str(item.get("branch_name") or "").strip()
            if not main_branch or not branch_name:
                raise RuntimeError(f"仓库 {name} 的分支元数据不完整")
            self._ensure_repo(repo)
            if not worktree.exists():
                raise RuntimeError(f"仓库 {name} 的会话 worktree 不存在")
            if self._run_git(repo, ["remote", "get-url", "origin"], check=False).returncode != 0:
                item.update({
                    "remote_status": "not_configured",
                    "push_status": "skipped",
                    "remote_error": "未配置 origin 远端，仅完成本地合并",
                })
                updated.append(item)
                continue

            dirty_main = self._run_git(repo, ["status", "--porcelain"], check=False).stdout.strip()
            if dirty_main:
                raise RuntimeError(f"仓库 {name} 的主工作区有未提交或未跟踪修改")
            dirty_task = self._run_git(worktree, ["status", "--porcelain"], check=False).stdout.strip()
            if dirty_task:
                raise RuntimeError(f"仓库 {name} 的会话 worktree 有未提交或未跟踪修改")

            auth_key = str(item.get("site_db_id") or item.get("site_id") or "")
            auth = remote_auth.get(auth_key) or remote_auth.get(str(item.get("site_id") or "")) or {}
            remote_sha, _ = self._fetch_remote_main(repo, main_branch, auth)

            current_main = self._run_git(repo, ["branch", "--show-current"], check=False).stdout.strip()
            if current_main != main_branch:
                switched = self._run_git(repo, ["switch", main_branch], check=False)
                if switched.returncode != 0:
                    error = switched.stderr or switched.stdout or "git switch failed"
                    raise RuntimeError(f"仓库 {name} 无法切换到主分支 {main_branch}: {self._safe_git_error(error)}")
            self._rebase_branch(repo, f"origin/{main_branch}", f"仓库 {name} 的主分支")

            current_task = self._run_git(worktree, ["branch", "--show-current"], check=False).stdout.strip()
            if current_task != branch_name:
                raise RuntimeError(f"仓库 {name} 的 worktree 未处于任务分支 {branch_name}")
            self._rebase_branch(worktree, main_branch, f"仓库 {name} 的任务分支")
            item.update({
                "remote_status": "synchronized",
                "push_status": "pending",
                "remote_before_sha": remote_sha,
                "main_before_sha": self._rev_parse(repo, main_branch),
                "branch_tip_sha": self._rev_parse(worktree, "HEAD"),
                "remote_error": "",
            })
            updated.append(item)
        return updated

    def push_completed_repositories(
        self,
        git_repos: list[dict[str, Any]],
        *,
        remote_auth: dict[str, dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Push merged main branches with a normal fast-forward push and verify remote SHAs."""

        remote_auth = remote_auth or {}
        for item in git_repos:
            repo = Path(str(item.get("repo_path") or ""))
            name = str(item.get("name") or item.get("site_id") or "仓库")
            main_branch = str(item.get("main_branch") or "").strip()
            has_origin = self._run_git(repo, ["remote", "get-url", "origin"], check=False).returncode == 0
            if str(item.get("remote_status") or "") == "not_configured" or not has_origin:
                item.update({
                    "remote_status": "not_configured",
                    "push_status": "skipped",
                    "remote_error": "未配置 origin 远端，仅完成本地合并",
                })
                continue
            auth_key = str(item.get("site_db_id") or item.get("site_id") or "")
            auth = remote_auth.get(auth_key) or remote_auth.get(str(item.get("site_id") or "")) or {}
            try:
                remote_before, resolved_auth = self._fetch_remote_main(repo, main_branch, auth)
                local_sha = self._rev_parse(repo, main_branch)
                can_fast_forward = self._run_git(
                    repo,
                    ["merge-base", "--is-ancestor", remote_before, local_sha],
                    check=False,
                )
                if can_fast_forward.returncode != 0:
                    raise RuntimeError(
                        f"仓库 {name} 的远端主分支在合并期间已更新，当前推送不是 fast-forward，请重试合并会话"
                    )
                with self._git_network_env(resolved_auth) as network_env:
                    pushed = self._run_git(
                        repo,
                        [
                            "-c",
                            "credential.helper=",
                            "push",
                            "--porcelain",
                            "origin",
                            f"refs/heads/{main_branch}:refs/heads/{main_branch}",
                        ],
                        check=False,
                        env=network_env,
                    )
                if pushed.returncode != 0:
                    error = pushed.stderr or pushed.stdout or "git push failed"
                    raise RuntimeError(f"仓库 {name} 推送主分支失败: {self._safe_git_error(error)}")
                remote_after, _ = self._fetch_remote_main(repo, main_branch, auth)
                if remote_after != local_sha:
                    raise RuntimeError(f"仓库 {name} 推送后远端 SHA 校验失败")
                item.update({
                    "remote_status": "verified",
                    "push_status": "pushed",
                    "remote_before_push_sha": remote_before,
                    "remote_after_sha": remote_after,
                    "main_after_sha": local_sha,
                    "remote_error": "",
                })
            except Exception as exc:
                item["push_status"] = "failed"
                item["remote_error"] = self._safe_git_error(str(exc))[:2000]
                raise
        return git_repos

    def _validated_cleanup_paths(
        self,
        *,
        project_id: str,
        conversation_id: str,
        worktree_root: str,
        item: dict[str, Any],
    ) -> tuple[Path, Path, Path]:
        project_root = project_service.project_root(project_id).resolve(strict=False)
        expected_root = (project_root / ".worktree" / conversation_id).resolve(strict=False)
        configured_root = Path(str(worktree_root or "")).resolve(strict=False)
        if configured_root != expected_root:
            raise RuntimeError("会话 worktree 根目录与项目元数据不一致")

        name = str(item.get("name") or "").strip()
        repo_value = str(item.get("repo_path") or "").strip()
        worktree_value = str(item.get("worktree_path") or "").strip()
        if not name or not repo_value or not worktree_value:
            raise RuntimeError("仓库清理元数据不完整")
        expected_repo = project_service.repo_root(project_id, name).resolve(strict=False)
        repo = Path(repo_value).resolve(strict=False)
        if repo != expected_repo:
            raise RuntimeError(f"仓库 {name} 路径与项目元数据不一致")
        expected_worktree = (expected_root / name).resolve(strict=False)
        worktree = Path(worktree_value).resolve(strict=False)
        if worktree != expected_worktree:
            raise RuntimeError(f"仓库 {name} worktree 路径不安全")
        if not repo.exists():
            raise RuntimeError(f"仓库 {name} 不存在")
        self._ensure_repo(repo)
        return expected_root, repo, worktree

    def cleanup_conversation_worktrees(
        self,
        *,
        project_id: str,
        conversation_id: str,
        provider: str,
        worktree_root: str,
        git_repos: list[dict[str, Any]],
        force: bool,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Remove conversation worktrees and local branches with strict ownership checks."""

        updated: list[dict[str, Any]] = []
        errors: list[str] = []
        expected_root: Path | None = None
        expected_prefix = f"{self._provider_prefix(provider)}/"
        for original in git_repos:
            item = dict(original)
            name = str(item.get("name") or item.get("site_id") or "仓库")
            try:
                root, repo, worktree = self._validated_cleanup_paths(
                    project_id=project_id,
                    conversation_id=conversation_id,
                    worktree_root=worktree_root,
                    item=item,
                )
                expected_root = root
                main_branch = str(item.get("main_branch") or "").strip()
                branch_name = str(item.get("branch_name") or "").strip()
                if not main_branch or not branch_name:
                    raise RuntimeError(f"仓库 {name} 分支元数据不完整")
                if branch_name == main_branch:
                    raise RuntimeError(f"拒绝删除仓库 {name} 的主分支")
                if not branch_name.startswith(expected_prefix):
                    raise RuntimeError(f"仓库 {name} 的任务分支前缀不匹配")
                valid = self._run_git(repo, ["check-ref-format", "--branch", branch_name], check=False)
                if valid.returncode != 0:
                    raise RuntimeError(f"仓库 {name} 的任务分支名称不合法")

                entries = self._worktree_entries(repo)
                if worktree.exists():
                    matching = next(
                        (
                            entry for entry in entries
                            if Path(entry.get("worktree") or "").resolve(strict=False) == worktree
                        ),
                        None,
                    )
                    if matching is None or matching.get("branch") != f"refs/heads/{branch_name}":
                        raise RuntimeError(f"仓库 {name} worktree 与任务分支不匹配")
                    dirty = bool(self._run_git(worktree, ["status", "--porcelain"], check=False).stdout.strip())
                    if dirty and not force:
                        raise RuntimeError(f"仓库 {name} worktree 仍有未提交修改")
                    args = ["worktree", "remove"]
                    if force:
                        args.append("--force")
                    args.extend(["--", str(worktree)])
                    self._run_git(repo, args)
                self._run_git(repo, ["worktree", "prune"], check=False)

                if self._local_branch_exists(repo, branch_name):
                    recorded_tip = str(item.get("branch_tip_sha") or "").strip()
                    current_tip = self._rev_parse(repo, branch_name)
                    if recorded_tip and current_tip != recorded_tip:
                        raise RuntimeError(f"仓库 {name} 的任务分支在清理前发生移动")
                    if not force and not self.is_merged(item):
                        raise RuntimeError(f"仓库 {name} 的任务分支尚未合并")
                    checked_out = any(
                        entry.get("branch") == f"refs/heads/{branch_name}"
                        for entry in self._worktree_entries(repo)
                    )
                    if checked_out:
                        raise RuntimeError(f"仓库 {name} 的任务分支仍被 worktree 使用")
                    self._run_git(repo, ["branch", "-D" if force else "-d", "--", branch_name])

                item.update({
                    "cleanup_status": "deleted",
                    "cleanup_error": "",
                    "worktree_deleted": True,
                    "branch_deleted": not self._local_branch_exists(repo, branch_name),
                })
            except Exception as exc:
                message = f"{name}: {exc}"
                errors.append(message)
                item.update({"cleanup_status": "failed", "cleanup_error": str(exc)[:1000]})
            updated.append(item)

        if expected_root is not None and expected_root.exists() and not errors:
            try:
                if force:
                    shutil.rmtree(expected_root)
                else:
                    expected_root.rmdir()
            except OSError as exc:
                errors.append(f"会话 worktree 根目录: {exc}")
        return updated, errors

    @staticmethod
    def _decode_limited(value: str, max_bytes: int = DIFF_MAX_BYTES) -> tuple[str, bool]:
        raw = value.encode("utf-8", errors="ignore")
        truncated = len(raw) > max_bytes
        if truncated:
            raw = raw[:max_bytes]
        return raw.decode("utf-8", errors="ignore"), truncated

    @staticmethod
    def _validated_relative_path(value: str) -> str:
        normalized = str(value or "").replace("\\", "/").strip()
        candidate = PurePosixPath(normalized)
        if (
            not normalized
            or "\x00" in normalized
            or candidate.is_absolute()
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise HTTPException(status_code=400, detail="文件路径不合法")
        return candidate.as_posix()

    @staticmethod
    def _decode_file_bytes(value: bytes) -> tuple[str, bool, bool]:
        binary = b"\x00" in value[:8192]
        truncated = len(value) > FILE_DIFF_MAX_BYTES
        if binary:
            return "", True, truncated
        visible = value[:FILE_DIFF_MAX_BYTES]
        return visible.decode("utf-8", errors="replace"), False, truncated

    @staticmethod
    def _parse_name_status(value: str) -> list[dict[str, str]]:
        files: list[dict[str, str]] = []
        for line in value.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            raw_status = parts[0].strip().upper()
            status = raw_status[:1] or "M"
            if status in {"R", "C"} and len(parts) >= 3:
                files.append({
                    "status": status,
                    "score": raw_status[1:],
                    "old_path": parts[1],
                    "path": parts[2],
                })
            else:
                files.append({"status": status, "path": parts[-1]})
        return files

    def _git_blob(self, repo: Path, revision: str, path: str) -> tuple[bytes, bool]:
        if not revision:
            return b"", False
        result = subprocess.run(
            ["git", "cat-file", "blob", f"{revision}:{path}"],
            cwd=str(repo),
            capture_output=True,
            env=self._git_env(),
        )
        if result.returncode != 0:
            return b"", False
        return result.stdout, True

    @staticmethod
    def _read_worktree_file(worktree: Path, path: str) -> tuple[bytes, bool]:
        candidate = worktree.joinpath(*PurePosixPath(path).parts)
        if candidate.is_symlink():
            return os.readlink(candidate).encode("utf-8", errors="replace"), True
        resolved_root = worktree.resolve(strict=False)
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="文件路径超出会话 worktree") from exc
        if not resolved.exists() or not resolved.is_file():
            return b"", False
        return resolved.read_bytes(), True

    def file_diff(
        self,
        *,
        project_id: str,
        conversation_id: str,
        worktree_root: str,
        item: dict[str, Any],
        file_meta: dict[str, Any],
    ) -> dict[str, Any]:
        """Return full before/after contents for a changed file with strict path validation."""

        _, repo, worktree = self._validated_cleanup_paths(
            project_id=project_id,
            conversation_id=conversation_id,
            worktree_root=worktree_root,
            item=item,
        )
        path = self._validated_relative_path(str(file_meta.get("path") or ""))
        old_path = self._validated_relative_path(str(file_meta.get("old_path") or path))
        status = str(file_meta.get("status") or "M").upper()
        branch_name = str(item.get("branch_name") or "").strip()
        branch_revision = (
            branch_name
            if branch_name and self._local_branch_exists(repo, branch_name)
            else str(item.get("branch_tip_sha") or "").strip()
        )
        if not branch_revision:
            raise RuntimeError("任务分支已删除且没有可用的文件快照")

        baseline_revision = str(item.get("main_before_sha") or item.get("main_branch") or "").strip()
        merge_base = self._run_git(
            repo,
            ["merge-base", baseline_revision, branch_revision],
            check=False,
        )
        if merge_base.returncode != 0 or not merge_base.stdout.strip():
            raise RuntimeError("无法确定文件对比基线")
        before_revision = merge_base.stdout.strip()

        before_bytes, before_exists = (b"", False)
        if not status.startswith("A"):
            before_bytes, before_exists = self._git_blob(repo, before_revision, old_path)

        after_bytes, after_exists = (b"", False)
        if not status.startswith("D"):
            if worktree.exists() and self._local_branch_exists(repo, branch_name):
                after_bytes, after_exists = self._read_worktree_file(worktree, path)
            else:
                after_bytes, after_exists = self._git_blob(repo, branch_revision, path)

        before, before_binary, before_truncated = self._decode_file_bytes(before_bytes)
        after, after_binary, after_truncated = self._decode_file_bytes(after_bytes)
        return {
            "site_id": str(item.get("site_id") or ""),
            "name": str(item.get("name") or ""),
            "path": path,
            "old_path": old_path,
            "status": status,
            "before": before,
            "after": after,
            "before_exists": before_exists,
            "after_exists": after_exists,
            "binary": before_binary or after_binary,
            "truncated": before_truncated or after_truncated,
            "before_revision": before_revision,
            "after_revision": branch_revision,
        }

    def repository_state(self, item: dict[str, Any]) -> dict[str, Any]:
        repo = Path(item["repo_path"])
        worktree = Path(item["worktree_path"])
        main_branch = str(item["main_branch"])
        branch_name = str(item["branch_name"])
        if item.get("cleanup_status") == "deleted" or not self._local_branch_exists(repo, branch_name):
            return {
                "site_id": item.get("site_id", ""),
                "name": item.get("name", ""),
                "main_branch": main_branch,
                "branch_name": branch_name,
                "ahead": 0,
                "behind": 0,
                "changed_files": 0,
                "insertions": 0,
                "deletions": 0,
                "files": [],
                "diff": "",
                "diff_truncated": False,
                "deleted": True,
                "read_only": True,
                "cleanup_status": item.get("cleanup_status") or "deleted",
                "cleanup_error": item.get("cleanup_error") or "",
                "branch_deleted": bool(item.get("branch_deleted", True)),
                "worktree_deleted": bool(item.get("worktree_deleted", True)),
                "remote_status": item.get("remote_status") or "unknown",
                "push_status": item.get("push_status") or "unknown",
                "remote_before_sha": item.get("remote_before_sha") or "",
                "remote_after_sha": item.get("remote_after_sha") or "",
                "remote_error": item.get("remote_error") or "",
            }
        counts = self._run_git(repo, ["rev-list", "--left-right", "--count", f"{main_branch}...{branch_name}"], check=False)
        behind = ahead = 0
        if counts.returncode == 0:
            parts = counts.stdout.strip().split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])

        diff_args = ["diff", "--no-color", "--no-ext-diff", "--unified=3", f"{main_branch}...{branch_name}"]
        patch = self._run_git(repo, diff_args, check=False).stdout
        if worktree.exists():
            working_patch = self._run_git(worktree, ["diff", "--no-color", "--no-ext-diff", "--unified=3", "HEAD"], check=False).stdout
            if working_patch:
                patch = f"{patch}\n{working_patch}" if patch else working_patch
        patch, diff_truncated = self._decode_limited(patch)

        name_status = self._run_git(repo, ["diff", "--name-status", f"{main_branch}...{branch_name}"], check=False).stdout
        files_by_path = {
            file["path"]: file
            for file in self._parse_name_status(name_status)
        }
        if worktree.exists():
            working_status = self._run_git(worktree, ["diff", "--name-status", "HEAD"], check=False).stdout
            for file in self._parse_name_status(working_status):
                existing = files_by_path.get(file["path"])
                if existing and existing.get("status") == "A":
                    continue
                files_by_path[file["path"]] = file
            untracked = self._run_git(
                worktree,
                ["ls-files", "--others", "--exclude-standard"],
                check=False,
            ).stdout
            for path in untracked.splitlines():
                if path:
                    files_by_path[path] = {"status": "A", "path": path}
        files = sorted(files_by_path.values(), key=lambda file: file["path"].lower())

        insertions = deletions = 0
        numstat = self._run_git(repo, ["diff", "--numstat", f"{main_branch}...{branch_name}"], check=False).stdout
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                if parts[0].isdigit():
                    insertions += int(parts[0])
                if parts[1].isdigit():
                    deletions += int(parts[1])

        return {
            "site_id": item.get("site_id", ""),
            "name": item.get("name", ""),
            "main_branch": main_branch,
            "branch_name": branch_name,
            "ahead": ahead,
            "behind": behind,
            "changed_files": len(files),
            "insertions": insertions,
            "deletions": deletions,
            "files": files,
            "diff": patch,
            "diff_truncated": diff_truncated,
            "deleted": False,
            "read_only": False,
            "cleanup_status": item.get("cleanup_status") or "retained",
            "cleanup_error": item.get("cleanup_error") or "",
            "branch_deleted": bool(item.get("branch_deleted", False)),
            "worktree_deleted": bool(item.get("worktree_deleted", False)),
            "remote_status": item.get("remote_status") or "unknown",
            "push_status": item.get("push_status") or "unknown",
            "remote_before_sha": item.get("remote_before_sha") or "",
            "remote_after_sha": item.get("remote_after_sha") or "",
            "remote_error": item.get("remote_error") or "",
        }

    def conversation_state(
        self,
        *,
        branch_name: str,
        provider: str,
        completion_status: str,
        worktree_root: str,
        git_repos: list[dict[str, Any]],
        diff_snapshot: dict[str, Any] | None = None,
        cleanup_status: str = "retained",
        cleanup_error: str = "",
    ) -> dict[str, Any]:
        live_repositories = [self.repository_state(item) for item in git_repos]
        snapshot_by_id = {
            str(item.get("site_id")): item
            for item in ((diff_snapshot or {}).get("repositories") or [])
        }
        if completion_status in {"merging", "completed", "discarded"} or cleanup_status != "retained":
            for repo in live_repositories:
                snapshot = snapshot_by_id.get(str(repo.get("site_id")))
                if snapshot:
                    repo.update({
                        key: snapshot.get(key, repo.get(key))
                        for key in (
                            "ahead",
                            "behind",
                            "changed_files",
                            "insertions",
                            "deletions",
                            "files",
                            "diff",
                            "diff_truncated",
                        )
                    })
                    repo["snapshot"] = True
        deleted = bool(live_repositories) and all(bool(repo.get("deleted")) for repo in live_repositories)
        read_only = deleted or completion_status in {"merging", "completed", "discarded"}
        return {
            "available": bool(git_repos),
            "live_available": bool(git_repos) and not deleted,
            "provider": provider,
            "branch_name": branch_name,
            "worktree_root": worktree_root,
            "completion_status": completion_status,
            "cleanup_status": cleanup_status,
            "cleanup_error": cleanup_error,
            "deleted": deleted,
            "read_only": read_only,
            "repositories": live_repositories,
        }

    def is_merged(self, item: dict[str, Any]) -> bool:
        repo = Path(item["repo_path"])
        branch_revision = str(item.get("branch_tip_sha") or item["branch_name"])
        result = self._run_git(
            repo,
            ["merge-base", "--is-ancestor", branch_revision, str(item["main_branch"])],
            check=False,
        )
        return result.returncode == 0

    def all_merged(self, git_repos: list[dict[str, Any]]) -> bool:
        return bool(git_repos) and all(self.is_merged(item) for item in git_repos)


conversation_git_service = ConversationGitService()
