from __future__ import annotations

import asyncio
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.core.celery_app import celery_app
from backend.core.redis_lock import acquire_site_lock, release_site_lock
from backend.models import AgentTask
from backend.models.enums import TaskStatus, SiteStatus
from backend.models.site import Site
from backend.services.execution_trace_service import redact_execution_text
from backend.tasks._helpers import task_db_session


async def _run_clone(task_id: str, *, retry_cb=None) -> dict[str, object]:
    """Async core of clone_repo_task — exposed for direct testing.

    retry_cb: callable invoked when site lock is unavailable; if None, raises RuntimeError.
              In the Celery wrapper, pass `self.retry`.
    """
    # 1) 取 task 基础信息 + lock
    async with task_db_session() as db:
        task = await db.get(AgentTask, task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        site_id_internal = str(task.site_id)

    if not acquire_site_lock(site_id_internal, task_id):
        if retry_cb is not None:
            raise retry_cb(countdown=30)
        raise RuntimeError(f"Could not acquire lock for site {site_id_internal}")

    try:
        # 2) 标记 running + 开始日志
        async with task_db_session() as db:
            task = await db.get(AgentTask, task_id)
            site = await db.get(Site, str(task.site_id))
            if site is None:
                raise ValueError(f"Site not found: {task.site_id}")

            payload = task.payload_json or {}
            git_url = payload.get("git_url", "")
            git_branch = payload.get("git_branch", "")
            git_username = payload.get("git_username", "")
            project_id = payload.get("project_id", "")
            repo_name = payload.get("repo_name", site.name)

            git_password = ""
            encrypted_pw = payload.get("git_password_encrypted", "")
            if encrypted_pw:
                from backend.core.encryption import decrypt_api_key
                git_password = decrypt_api_key(encrypted_pw)

            task.status = TaskStatus.RUNNING.value
            task.started_at = datetime.now(timezone.utc)
            await db.commit()

            from backend.services.task_service import task_service
            from backend.services.site_service import site_service
            await task_service.append_log(
                db, task,
                f"开始克隆 {redact_execution_text(site_service.sanitize_git_url(git_url))} "
                f"(branch={git_branch or 'default'})",
                level="INFO", source="clone",
            )

        # 3) 跑 git clone（流式抓输出）
        from backend.services.site_service import site_service
        from backend.services.project_service import project_service

        clone_root = (
            project_service.repo_root(project_id, repo_name) if project_id
            else site_service.site_root(site.site_id)
        )

        git_bin = shutil.which("git")
        if not git_bin:
            raise RuntimeError("git is required in the runtime image to clone site repositories")

        # 清理目标目录（如果存在）
        if Path(clone_root).exists():
            shutil.rmtree(clone_root, ignore_errors=True)
        Path(clone_root).parent.mkdir(parents=True, exist_ok=True)

        embedded_username, embedded_password = site_service.git_url_credentials(git_url)
        git_username = git_username or embedded_username
        git_password = git_password or embedded_password
        public_url = site_service.sanitize_git_url(git_url)
        cmd = [git_bin, "-c", "credential.helper=", "clone", "--progress"]
        if git_branch:
            cmd.extend(["--branch", git_branch, "--single-branch"])
        cmd.extend([public_url, str(clone_root)])

        with site_service.git_network_env(git_username, git_password) as network_env:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=network_env,
            )
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line = raw.rstrip("\r\n")
                    if not line:
                        continue
                    line = redact_execution_text(line)
                    # 短事务写一条日志（让 WS 立即看到）
                    async with task_db_session() as db:
                        task = await db.get(AgentTask, task_id)
                        from backend.services.task_service import task_service
                        await task_service.append_log(
                            db, task, line, level="INFO", source="git",
                        )
                rc = proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

        # 4) 收尾
        async with task_db_session() as db:
            task = await db.get(AgentTask, task_id)
            site = await db.get(Site, str(task.site_id))
            from backend.services.task_service import task_service

            if rc == 0:
                # 校验 .git 目录存在
                if not (Path(clone_root) / ".git").exists():
                    site.status = SiteStatus.ERROR.value
                    task.status = TaskStatus.FAILED.value
                    task.error = "Cloned repository is missing .git metadata"
                    task.finished_at = datetime.now(timezone.utc)
                    await task_service.append_log(
                        db, task, task.error, level="ERROR", source="clone",
                    )
                    await db.commit()
                    raise RuntimeError(task.error)

                normalized = subprocess.run(
                    [git_bin, "remote", "set-url", "origin", public_url],
                    cwd=str(clone_root),
                    capture_output=True,
                    text=True,
                )
                if normalized.returncode != 0:
                    site.status = SiteStatus.ERROR.value
                    task.status = TaskStatus.FAILED.value
                    task.error = "Failed to normalize cloned repository origin URL"
                    task.finished_at = datetime.now(timezone.utc)
                    await task_service.append_log(db, task, task.error, level="ERROR", source="clone")
                    await db.commit()
                    raise RuntimeError(task.error)

                # 让 site_service 补全文档/np 目录
                site_service._ensure_docs_structure(Path(clone_root))
                site_service._ensure_np_structure(Path(clone_root))
                branch_result = subprocess.run(
                    [git_bin, "branch", "--show-current"],
                    cwd=str(clone_root),
                    capture_output=True,
                    text=True,
                )
                site.main_branch = git_branch or (branch_result.stdout.strip() if branch_result.returncode == 0 else "")

                site.status = SiteStatus.STOPPED.value
                task.status = TaskStatus.SUCCESS.value
                task.finished_at = datetime.now(timezone.utc)
                await task_service.append_log(
                    db, task, "克隆完成", level="INFO", source="clone",
                )
            else:
                site.status = SiteStatus.ERROR.value
                task.status = TaskStatus.FAILED.value
                task.error = f"git clone 退出码 {rc}"
                task.finished_at = datetime.now(timezone.utc)
                await task_service.append_log(
                    db, task, task.error, level="ERROR", source="clone",
                )
                await db.commit()
                raise RuntimeError(task.error)

            await db.commit()
            return task_service.serialize_task(task)
    finally:
        release_site_lock(site_id_internal, task_id)


@celery_app.task(bind=True, max_retries=60, default_retry_delay=30)
def clone_repo_task(self, task_id: str) -> dict[str, object]:
    return asyncio.run(_run_clone(task_id, retry_cb=self.retry))
