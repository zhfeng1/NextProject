from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select

from backend.core.celery_app import celery_app
from backend.core.config import get_settings
from backend.core.encryption import decrypt_api_key
from backend.core.redis_lock import acquire_site_lock, release_site_lock
from backend.models import Site, Task, TaskStatus, TechPlatformDeploymentModule
from backend.services.execution_trace_service import redact_execution_text
from backend.services.project_service import project_service
from backend.services.site_service import site_service
from backend.services.task_service import task_service
from backend.services.tech_platform_client import required_resource_types
from backend.services.tech_platform_deploy_service import (
    RESOURCE_ORDER,
    TechPlatformResourceError,
    tech_platform_deploy_service,
    validate_and_deploy_resources,
)
from backend.tasks._helpers import task_db_session


async def _docker_login(
    *, registry: str, username: str, password: str, docker_config: str
) -> None:
    if not shutil.which("docker"):
        raise RuntimeError("Celery 运行镜像中缺少 docker 命令")
    if not registry or "://" in registry:
        raise RuntimeError(
            "HARBOR_REGISTRY 必须是 registry 主机名，不能包含 URL scheme"
        )
    if not username or not password:
        raise RuntimeError("HARBOR_USERNAME/HARBOR_PASSWORD 未配置")
    env = {**os.environ, "DOCKER_CONFIG": docker_config}
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "login",
        registry,
        "--username",
        username,
        "--password-stdin",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    try:
        output, _ = await asyncio.wait_for(
            proc.communicate((password + "\n").encode()), timeout=60
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("Harbor 登录超时")
    if proc.returncode != 0:
        detail = redact_execution_text(output.decode("utf-8", errors="ignore"))[-600:]
        raise RuntimeError(f"Harbor 登录失败: {detail}")


async def _git_credentials(db: Any, site_id: str) -> tuple[str, str]:
    rows = await db.execute(
        select(Task)
        .where(Task.site_id == site_id, Task.task_type == "clone_repo")
        .order_by(desc(Task.created_at))
        .limit(1)
    )
    clone_task = rows.scalar_one_or_none()
    if clone_task is None:
        return "", ""
    payload = clone_task.payload_json or {}
    password = ""
    if payload.get("git_password_encrypted"):
        password = decrypt_api_key(str(payload["git_password_encrypted"]))
    return str(payload.get("git_username") or ""), password


async def _prepare_checkout(
    db: Any,
    task: Task,
    site: Site,
    snapshot: dict[str, Any],
    repo_root: Path,
    checkout_root: Path,
) -> str:
    if not (repo_root / ".git").exists():
        raise RuntimeError("部署仓库缺少 Git 元数据")
    branch = str(snapshot.get("main_branch") or site.main_branch or "").strip()
    if not branch:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        branch = result.stdout.strip() if result.returncode == 0 else ""

    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    commit_ref = "HEAD"
    if remote.returncode == 0 and remote.stdout.strip():
        if not branch:
            raise RuntimeError("仓库配置了远端，但没有可用的主分支")
        username, password = await _git_credentials(db, str(site.id))
        with site_service.git_network_env(username, password) as git_env:
            code, _ = await task_service.run_shell_command(
                db,
                task,
                ["git", "fetch", "--prune", "origin", branch],
                cwd=repo_root,
                timeout_sec=300,
                extra_env=git_env,
                log_source="git",
                command_preview=f"$ git fetch --prune origin {branch}",
            )
        if code != 0:
            raise RuntimeError(f"拉取主分支 {branch} 失败")
        commit_ref = "FETCH_HEAD"
    else:
        await task_service.append_log(
            db, task, "仓库没有 origin，使用本地 HEAD 构建", "WARN", source="git"
        )

    result = subprocess.run(
        ["git", "rev-parse", commit_ref],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("无法解析部署 Commit")
    commit_sha = result.stdout.strip()
    code, _ = await task_service.run_shell_command(
        db,
        task,
        ["git", "worktree", "add", "--detach", str(checkout_root), commit_sha],
        cwd=repo_root,
        timeout_sec=120,
        log_source="git",
        command_preview=f"$ git worktree add --detach [temporary checkout] {commit_sha[:12]}",
    )
    if code != 0:
        raise RuntimeError("创建部署快照失败")
    return commit_sha


async def _run_tech_platform_deploy(
    task_id: str, *, retry_cb=None
) -> dict[str, object]:
    async with task_db_session() as db:
        task = await db.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        module_id = str((task.payload_json or {}).get("module_id") or "")
        if not module_id:
            raise ValueError("部署任务缺少 module_id")

    lock_id = f"tech-platform-module:{module_id}"
    if not acquire_site_lock(lock_id, task_id):
        if retry_cb is not None:
            raise retry_cb(countdown=30)
        raise RuntimeError(f"Could not acquire lock for module {module_id}")

    checkout_base = Path(tempfile.mkdtemp(prefix="nextproject-tech-deploy-"))
    checkout_root = checkout_base / "checkout"
    docker_config_dir = tempfile.mkdtemp(prefix="nextproject-docker-config-")
    repo_root: Path | None = None
    image = ""
    commit_sha = ""
    deployed: list[str] = []
    failed_resource = ""
    failure_phase = ""
    try:
        async with task_db_session() as db:
            task = await db.get(Task, task_id)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            module = await db.get(TechPlatformDeploymentModule, module_id)
            site = await db.get(Site, task.site_id)
            if module is None or site is None:
                raise ValueError("部署模块或仓库不存在")
            snapshot = dict((task.payload_json or {}).get("snapshot") or {})
            if not snapshot:
                raise ValueError("部署任务缺少不可变配置快照")

            await task_service.update_status(db, task, TaskStatus.RUNNING)
            module.status = "running"
            module.last_error = ""
            await db.commit()
            await task_service.append_log(
                db, task, "[1/7] 拉取代码并冻结部署 Commit", source="deploy"
            )

            repo_root = project_service.repo_root(str(module.project_id), site.name)
            commit_sha = await _prepare_checkout(
                db, task, site, snapshot, repo_root, checkout_root
            )
            module.last_commit_sha = commit_sha
            snapshot["commit_sha"] = commit_sha
            task_payload = dict(task.payload_json or {})
            task_payload["snapshot"] = snapshot
            task.payload_json = task_payload
            await db.commit()
            await task_service.append_log(
                db, task, f"部署 Commit: {commit_sha}", source="git"
            )

            dockerfile = tech_platform_deploy_service.resolve_repo_path(
                checkout_root,
                str(snapshot["dockerfile_path"]),
                field="Dockerfile",
                kind="file",
            )
            build_context = tech_platform_deploy_service.resolve_repo_path(
                checkout_root,
                str(snapshot["build_context"]),
                field="构建上下文",
                kind="dir",
            )
            settings = get_settings()
            image = str(snapshot["image"])

            await task_service.append_log(
                db, task, f"[2/7] 登录 Harbor 并构建镜像 {image}", source="deploy"
            )
            await _docker_login(
                registry=str(snapshot["harbor_registry"]),
                username=settings.harbor_username,
                password=settings.harbor_password,
                docker_config=docker_config_dir,
            )
            docker_env = {"DOCKER_CONFIG": docker_config_dir}
            code, _ = await task_service.run_shell_command(
                db,
                task,
                [
                    "docker",
                    "build",
                    "--force-rm",
                    "--provenance=false",
                    "--platform",
                    str(snapshot["docker_build_platform"]),
                    "-t",
                    image,
                    "-f",
                    str(dockerfile),
                    str(build_context),
                ],
                cwd=checkout_root,
                timeout_sec=settings.default_task_timeout_seconds,
                extra_env=docker_env,
                log_source="docker",
                command_preview=(
                    f"$ docker build --platform {snapshot['docker_build_platform']} -t {image} "
                    f"-f {snapshot['dockerfile_path']} {snapshot['build_context']}"
                ),
            )
            if code != 0:
                raise RuntimeError(f"Docker 构建失败，退出码 {code}")

            await task_service.append_log(
                db, task, "[3/7] 推送镜像到 Harbor", source="deploy"
            )
            code, _ = await task_service.run_shell_command(
                db,
                task,
                ["docker", "push", image],
                cwd=checkout_root,
                timeout_sec=settings.default_task_timeout_seconds,
                extra_env=docker_env,
                log_source="docker",
            )
            if code != 0:
                raise RuntimeError(f"Docker 推送失败，退出码 {code}")
            module.last_image = image
            await db.commit()

            await task_service.append_log(
                db, task, "[4/7] 登录技术中台并同步应用", source="deploy"
            )
            async with tech_platform_deploy_service.client() as client:
                await client.login()
                await task_service.append_log(
                    db, task, "技术中台登录成功", source="platform"
                )
                current_app_id = module.platform_app_id or str(
                    snapshot.get("platform_app_id") or ""
                )
                app_id, _ = await client.save_application(
                    app_id=current_app_id,
                    app_name=str(snapshot["app_name"]),
                    harbor_project=str(snapshot["harbor_project"]),
                    repository_name=str(snapshot["repository_name"]),
                    image_tag=str(snapshot["image_tag"]),
                    app_type=str(snapshot["app_type"]),
                )
                module.platform_app_id = app_id
                await db.commit()
                await task_service.append_log(
                    db, task, f"中台应用已同步，appId={app_id}", source="platform"
                )

                await task_service.append_log(
                    db, task, "[5/7] 获取中台 YAML 类型模板", source="deploy"
                )
                resource_types = required_resource_types(
                    await client.get_yaml_resource_types(), RESOURCE_ORDER
                )
                resources = tech_platform_deploy_service.render_templates(
                    snapshot, image=image
                )

                await task_service.append_log(
                    db, task, "[6/7] 校验全部 YAML 资源", source="deploy"
                )

                async def on_validated(kind: str) -> None:
                    await task_service.append_log(
                        db, task, f"{kind} 校验通过", source="platform"
                    )

                async def on_validation_complete() -> None:
                    await task_service.append_log(
                        db, task, "[7/7] 按顺序部署 YAML 资源", source="deploy"
                    )

                async def on_deployed(kind: str) -> None:
                    await task_service.append_log(
                        db, task, f"{kind} 部署完成", source="platform"
                    )

                deployed = await validate_and_deploy_resources(
                    client,
                    app_id=app_id,
                    resources=resources,
                    resource_types=resource_types,
                    on_validated=on_validated,
                    on_validation_complete=on_validation_complete,
                    on_deployed=on_deployed,
                )

            module.status = "success"
            module.last_error = ""
            module.last_deployed_at = datetime.now(timezone.utc)
            await db.commit()
            result = {
                "ok": True,
                "module_id": module_id,
                "app_id": module.platform_app_id,
                "image": image,
                "commit_sha": commit_sha,
                "deployed_resources": deployed,
            }
            await task_service.update_status(
                db, task, TaskStatus.SUCCESS, result=result
            )
            await task_service.append_log(db, task, "技术中台部署完成", source="deploy")
            return task_service.serialize_task(task)
    except Exception as exc:
        if isinstance(exc, TechPlatformResourceError):
            deployed = exc.deployed_resources
            failed_resource = exc.kind
            failure_phase = exc.phase
        message = redact_execution_text(str(exc))[:2000]
        async with task_db_session() as db:
            task = await db.get(Task, task_id)
            module = await db.get(TechPlatformDeploymentModule, module_id)
            if module is not None:
                module.status = "failed"
                module.last_error = message
                if image:
                    module.last_image = image
                await db.commit()
            if task is not None:
                await task_service.append_log(
                    db, task, f"部署失败: {message}", "ERROR", source="deploy"
                )
                await task_service.update_status(
                    db,
                    task,
                    TaskStatus.FAILED,
                    error=message,
                    result={
                        "ok": False,
                        "module_id": module_id,
                        "image": image,
                        "commit_sha": commit_sha,
                        "deployed_resources": deployed,
                        "failed_resource": failed_resource,
                        "failure_phase": failure_phase,
                    },
                )
        raise
    finally:
        if image and shutil.which("docker"):
            subprocess.run(
                ["docker", "image", "rm", image],
                env={**os.environ, "DOCKER_CONFIG": docker_config_dir},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        if repo_root is not None and checkout_root.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(checkout_root)],
                cwd=str(repo_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            with suppress(Exception):
                subprocess.run(
                    ["git", "worktree", "prune"],
                    cwd=str(repo_root),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        shutil.rmtree(checkout_base, ignore_errors=True)
        shutil.rmtree(docker_config_dir, ignore_errors=True)
        release_site_lock(lock_id, task_id)


@celery_app.task(bind=True, max_retries=60, default_retry_delay=30)
def tech_platform_deploy_task(self, task_id: str) -> dict[str, object]:
    return asyncio.run(_run_tech_platform_deploy(task_id, retry_cb=self.retry))


@celery_app.task(bind=True, max_retries=1)
def deploy_task(self, task_id: str) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        async with task_db_session() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return {"ok": False, "message": "task not found"}
            site = await db.get(Site, task.site_id)
            if site is None:
                return {"ok": False, "message": "site not found"}
            await task_service.update_status(db, task, TaskStatus.RUNNING)
            if task.task_type == "deploy_local":
                await site_service.restart_site(
                    db,
                    site.site_id,
                    type(
                        "UserRef",
                        (),
                        {
                            "id": site.owner_id,
                            "default_org_id": site.org_id,
                            "is_superuser": True,
                        },
                    )(),
                )
                await task_service.update_status(
                    db,
                    task,
                    TaskStatus.SUCCESS,
                    result={
                        "ok": True,
                        "preview_url": site_service.preview_url_for_site(site.site_id),
                    },
                )
            else:
                await task_service.update_status(
                    db,
                    task,
                    TaskStatus.SUCCESS,
                    result={
                        "ok": True,
                        "target": "apollo",
                        "message": "Apollo deploy request accepted",
                    },
                )
            return task_service.serialize_task(task)

    return asyncio.run(_run())
