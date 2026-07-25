from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from backend.models import Site
from backend.services.conversation_git_service import conversation_git_service


COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


@dataclass(frozen=True)
class SiteVersionCommit:
    repo: Path
    branch: str
    before_sha: str
    commit_sha: str
    tag_name: str
    diff_summary: dict[str, Any]
    initialized_repository: bool = False


class SiteVersionGitService:
    @staticmethod
    def _git_env() -> dict[str, str]:
        return {
            **os.environ,
            "GIT_AUTHOR_NAME": "NextProject",
            "GIT_AUTHOR_EMAIL": "bot@nextproject",
            "GIT_COMMITTER_NAME": "NextProject",
            "GIT_COMMITTER_EMAIL": "bot@nextproject",
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
            timeout=30,
        )
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "Git operation failed").strip()
            raise RuntimeError(message[:2000])
        return result

    def _head_sha(self, repo: Path) -> str:
        result = self._run_git(repo, ["rev-parse", "--verify", "HEAD^{commit}"], check=False)
        sha = result.stdout.strip().lower()
        return sha if result.returncode == 0 and COMMIT_SHA_PATTERN.fullmatch(sha) else ""

    def _current_branch(self, repo: Path) -> str:
        branch = self._run_git(repo, ["branch", "--show-current"], check=False).stdout.strip()
        if not branch:
            branch = self._run_git(repo, ["symbolic-ref", "--short", "HEAD"], check=False).stdout.strip()
        if not branch:
            raise HTTPException(status_code=409, detail="站点仓库当前不在可写分支上")
        return branch

    def prepare_repository(self, site: Site, repo: Path) -> tuple[str, bool]:
        git_bin = shutil.which("git")
        if not git_bin:
            raise RuntimeError("git is required in the runtime image for site versions")
        repo.mkdir(parents=True, exist_ok=True)
        initialized = False
        if not (repo / ".git").exists():
            if getattr(site, "project_id", None):
                raise HTTPException(status_code=409, detail="项目仓库缺少 Git 元数据，不能创建版本")
            self._run_git(repo, ["init", "-b", "main"])
            initialized = True

        inside = self._run_git(repo, ["rev-parse", "--is-inside-work-tree"], check=False)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            raise HTTPException(status_code=409, detail="站点目录不是有效的 Git 仓库")

        if initialized or not self._head_sha(repo):
            branch = self._current_branch(repo)
        else:
            branch = conversation_git_service.resolve_main_branch(site, repo)
            current = self._current_branch(repo)
            if current != branch:
                raise HTTPException(status_code=409, detail=f"站点仓库必须位于主分支 {branch} 才能创建版本")
        return branch, initialized

    @staticmethod
    def tag_name(version_number: int) -> str:
        return f"nextproject/version/v{version_number}"

    def _diff_summary(self, repo: Path, before_sha: str, after_sha: str) -> dict[str, int]:
        base = before_sha or EMPTY_TREE_SHA
        result = self._run_git(repo, ["diff", "--numstat", base, after_sha])
        files_changed = 0
        insertions = 0
        deletions = 0
        for line in result.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            added, removed, _path = parts
            files_changed += 1
            if added.isdigit():
                insertions += int(added)
            if removed.isdigit():
                deletions += int(removed)
        return {
            "files_changed": files_changed,
            "insertions": insertions,
            "deletions": deletions,
        }

    def _commit(self, repo: Path, message: str) -> str:
        self._run_git(
            repo,
            [
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "--no-verify",
                "-m",
                message,
            ],
        )
        sha = self._head_sha(repo)
        if not sha:
            raise RuntimeError("Git commit completed without a valid Commit SHA")
        return sha

    def _create_tag(self, repo: Path, tag_name: str, commit_sha: str) -> None:
        exists = self._run_git(repo, ["show-ref", "--verify", "--quiet", f"refs/tags/{tag_name}"], check=False)
        if exists.returncode == 0:
            raise HTTPException(status_code=409, detail=f"版本标签已存在: {tag_name}")
        self._run_git(repo, ["tag", tag_name, commit_sha])

    def create_snapshot(
        self,
        *,
        site: Site,
        repo: Path,
        version_number: int,
        message: str,
    ) -> SiteVersionCommit:
        branch, initialized = self.prepare_repository(site, repo)
        before_sha = self._head_sha(repo)
        tag_name = self.tag_name(version_number)
        try:
            self._run_git(repo, ["add", "-A"])
            commit_sha = self._commit(repo, message)
            self._create_tag(repo, tag_name, commit_sha)
        except Exception:
            if initialized:
                shutil.rmtree(repo / ".git", ignore_errors=True)
            elif before_sha:
                self._run_git(repo, ["reset", "--mixed", before_sha], check=False)
            raise
        return SiteVersionCommit(
            repo=repo,
            branch=branch,
            before_sha=before_sha,
            commit_sha=commit_sha,
            tag_name=tag_name,
            diff_summary=self._diff_summary(repo, before_sha, commit_sha),
            initialized_repository=initialized,
        )

    def validate_version_target(self, repo: Path, version_number: int, commit_sha: str) -> str:
        normalized = (commit_sha or "").strip().lower()
        if not COMMIT_SHA_PATTERN.fullmatch(normalized):
            raise HTTPException(status_code=409, detail="版本记录中的 Commit SHA 无效")
        commit = self._run_git(repo, ["rev-parse", "--verify", f"{normalized}^{{commit}}"], check=False)
        if commit.returncode != 0:
            raise HTTPException(status_code=404, detail="版本对应的 Git Commit 已不存在")
        tag_name = self.tag_name(version_number)
        tagged = self._run_git(repo, ["rev-list", "-n", "1", tag_name], check=False)
        if tagged.returncode != 0 or tagged.stdout.strip().lower() != normalized:
            raise HTTPException(status_code=409, detail="版本标签与数据库 Commit 不一致")
        return normalized

    def create_rollback(
        self,
        *,
        site: Site,
        repo: Path,
        target_version_number: int,
        target_commit_sha: str,
        new_version_number: int,
        message: str,
    ) -> SiteVersionCommit:
        branch, initialized = self.prepare_repository(site, repo)
        if initialized:
            shutil.rmtree(repo / ".git", ignore_errors=True)
            raise HTTPException(status_code=409, detail="站点尚无可回滚的 Git 仓库")
        dirty = self._run_git(repo, ["status", "--porcelain", "--untracked-files=normal"]).stdout.strip()
        if dirty:
            raise HTTPException(status_code=409, detail="站点存在未提交或未跟踪修改，不能回滚")

        target_sha = self.validate_version_target(repo, target_version_number, target_commit_sha)
        before_sha = self._head_sha(repo)
        tag_name = self.tag_name(new_version_number)
        try:
            self._run_git(repo, ["read-tree", "--reset", "-u", target_sha])
            commit_sha = self._commit(repo, message)
            self._create_tag(repo, tag_name, commit_sha)
        except Exception:
            if before_sha:
                self._run_git(repo, ["reset", "--hard", before_sha], check=False)
            raise
        return SiteVersionCommit(
            repo=repo,
            branch=branch,
            before_sha=before_sha,
            commit_sha=commit_sha,
            tag_name=tag_name,
            diff_summary=self._diff_summary(repo, before_sha, commit_sha),
        )

    def compensate(self, commit: SiteVersionCommit, *, preserve_worktree: bool) -> None:
        self._run_git(commit.repo, ["tag", "-d", commit.tag_name], check=False)
        if commit.initialized_repository:
            shutil.rmtree(commit.repo / ".git", ignore_errors=True)
            return
        if not commit.before_sha or self._head_sha(commit.repo) != commit.commit_sha:
            return
        mode = "--mixed" if preserve_worktree else "--hard"
        self._run_git(commit.repo, ["reset", mode, commit.before_sha], check=False)


site_version_git_service = SiteVersionGitService()
