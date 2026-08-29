from __future__ import annotations

import re
import subprocess
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from fastapi import HTTPException
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.models import Site, Task, TaskStatus, TechPlatformDeploymentModule
from backend.schemas.tech_platform import (
    TechPlatformModuleCreate,
    TechPlatformModuleUpdate,
)
from backend.services.project_service import project_service
from backend.services.site_service import site_service
from backend.services.task_service import task_service
from backend.services.tech_platform_client import (
    TechPlatformClient,
    TechPlatformError,
    required_resource_types,
)


RESOURCE_ORDER = ("ConfigMap", "Deployment", "Service")
IGNORED_SCAN_DIRS = {
    ".git",
    "node_modules",
    ".next",
    "dist",
    "build",
    "target",
    "vendor",
}
DNS_LABEL_RE = re.compile(r"[^a-z0-9-]+")

DEFAULT_CONFIG_MAP_TEMPLATE = """apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ app_name }}
  namespace: {{ namespace }}
data: {}
"""

DEFAULT_DEPLOYMENT_TEMPLATE = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ app_name }}
  namespace: {{ namespace }}
spec:
  replicas: 1
  revisionHistoryLimit: 2
  selector:
    matchLabels:
      app: {{ app_name }}
  template:
    metadata:
      labels:
        app: {{ app_name }}
      namespace: {{ namespace }}
    spec:
      containers:
        - name: {{ app_name }}
          image: {{ image }}
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: {{ container_port }}
              protocol: TCP
          livenessProbe:
            tcpSocket:
              port: {{ container_port }}
            failureThreshold: 3
            successThreshold: 1
            initialDelaySeconds: 30
            periodSeconds: 60
"""

DEFAULT_SERVICE_TEMPLATE = """apiVersion: v1
kind: Service
metadata:
  name: {{ app_name }}
  namespace: {{ namespace }}
spec:
  selector:
    app: {{ app_name }}
  ports:
    - name: http
      port: {{ service_port }}
      targetPort: {{ container_port }}
"""


class TechPlatformResourceError(RuntimeError):
    def __init__(
        self,
        *,
        phase: str,
        kind: str,
        deployed_resources: list[str],
        cause: Exception,
    ) -> None:
        self.phase = phase
        self.kind = kind
        self.deployed_resources = list(deployed_resources)
        phase_label = "校验" if phase == "validate" else "部署"
        super().__init__(f"{kind} {phase_label}失败: {cause}")


async def validate_and_deploy_resources(
    client: TechPlatformClient,
    *,
    app_id: str,
    resources: list[dict[str, str]],
    resource_types: dict[str, int],
    on_validated: Callable[[str], Awaitable[None]] | None = None,
    on_validation_complete: Callable[[], Awaitable[None]] | None = None,
    on_deployed: Callable[[str], Awaitable[None]] | None = None,
) -> list[str]:
    """Validate the complete set before deploying any resource."""
    for resource in resources:
        kind = resource["kind"]
        try:
            await client.check_yaml(
                app_id=app_id,
                kind=kind,
                resource_type=resource_types[kind],
                yaml_text=resource["yaml"],
            )
        except Exception as exc:
            raise TechPlatformResourceError(
                phase="validate", kind=kind, deployed_resources=[], cause=exc
            ) from exc
        if on_validated is not None:
            await on_validated(kind)

    if on_validation_complete is not None:
        await on_validation_complete()

    deployed: list[str] = []
    for resource in resources:
        kind = resource["kind"]
        try:
            await client.deploy_yaml(
                app_id=app_id,
                kind=kind,
                resource_type=resource_types[kind],
                yaml_text=resource["yaml"],
            )
        except Exception as exc:
            raise TechPlatformResourceError(
                phase="deploy", kind=kind, deployed_resources=deployed, cause=exc
            ) from exc
        deployed.append(kind)
        if on_deployed is not None:
            await on_deployed(kind)
    return deployed


class TechPlatformDeployService:
    def __init__(self) -> None:
        self.template_env = SandboxedEnvironment(
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )

    @staticmethod
    def normalize_relative_path(value: str, *, field: str) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        path = PurePosixPath(raw)
        if not raw or path.is_absolute() or ".." in path.parts:
            raise HTTPException(status_code=400, detail=f"{field} 必须是仓库内相对路径")
        normalized = path.as_posix()
        return "." if normalized in {"", "."} else normalized.removeprefix("./")

    def resolve_repo_path(
        self,
        repo_root: Path,
        value: str,
        *,
        field: str,
        kind: str,
        must_exist: bool = True,
    ) -> Path:
        normalized = self.normalize_relative_path(value, field=field)
        root = repo_root.resolve()
        candidate = (root / normalized).resolve(strict=False)
        if candidate != root and root not in candidate.parents:
            raise HTTPException(status_code=400, detail=f"{field} 不能越过仓库目录")
        if must_exist and not candidate.exists():
            raise HTTPException(status_code=400, detail=f"{field} 不存在: {normalized}")
        if must_exist and kind == "file" and not candidate.is_file():
            raise HTTPException(status_code=400, detail=f"{field} 必须是文件")
        if must_exist and kind == "dir" and not candidate.is_dir():
            raise HTTPException(status_code=400, detail=f"{field} 必须是目录")
        return candidate

    @staticmethod
    def _dns_label(value: str) -> str:
        normalized = DNS_LABEL_RE.sub("-", value.lower().replace("_", "-")).strip("-")
        normalized = re.sub(r"-+", "-", normalized)[:63].rstrip("-")
        return normalized or "app"

    def default_module_name(self, site: Site, dockerfile_path: str) -> str:
        path = PurePosixPath(dockerfile_path)
        suffix = ""
        if path.name.startswith("Dockerfile."):
            suffix = path.name.removeprefix("Dockerfile.")
        elif path.parent.as_posix() not in {"", "."}:
            suffix = path.parent.name
        base = (
            site.name if not suffix or suffix == site.name else f"{site.name}-{suffix}"
        )
        return self._dns_label(base)

    @staticmethod
    def default_templates() -> dict[str, str]:
        return {
            "config_map_template": DEFAULT_CONFIG_MAP_TEMPLATE,
            "deployment_template": DEFAULT_DEPLOYMENT_TEMPLATE,
            "service_template": DEFAULT_SERVICE_TEMPLATE,
        }

    def render_templates(
        self,
        module: TechPlatformDeploymentModule | dict[str, Any],
        *,
        image: str,
    ) -> list[dict[str, str]]:
        get_value = (
            module.get if isinstance(module, dict) else lambda key: getattr(module, key)
        )
        variables = {
            "app_name": get_value("app_name"),
            "namespace": get_value("namespace"),
            "image": image,
            "container_port": get_value("container_port"),
            "service_port": get_value("service_port"),
            "harbor_project": get_value("harbor_project"),
            "repository_name": get_value("repository_name"),
        }
        template_fields = (
            ("ConfigMap", "config_map_template"),
            ("Deployment", "deployment_template"),
            ("Service", "service_template"),
        )
        rendered: list[dict[str, str]] = []
        for expected_kind, field in template_fields:
            source = str(get_value(field) or "")
            if not source.strip():
                raise HTTPException(
                    status_code=400, detail=f"{expected_kind} 模板不能为空"
                )
            try:
                yaml_text = self.template_env.from_string(source).render(**variables)
            except TemplateError as exc:
                raise HTTPException(
                    status_code=400, detail=f"{expected_kind} 模板渲染失败: {exc}"
                ) from exc
            try:
                documents = list(yaml.safe_load_all(yaml_text))
            except yaml.YAMLError as exc:
                raise HTTPException(
                    status_code=400, detail=f"{expected_kind} YAML 无效: {exc}"
                ) from exc
            if len(documents) != 1 or not isinstance(documents[0], dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"{expected_kind} 模板必须只包含一个 YAML 资源",
                )
            actual_kind = str(documents[0].get("kind") or "")
            if actual_kind != expected_kind:
                raise HTTPException(
                    status_code=400,
                    detail=f"{expected_kind} 模板的 kind 必须为 {expected_kind}，当前为 {actual_kind or '空'}",
                )
            rendered.append({"kind": expected_kind, "yaml": yaml_text})
        return rendered

    def client(self) -> TechPlatformClient:
        settings = get_settings()
        return TechPlatformClient(
            base_url=settings.tech_platform_base_url,
            username=settings.tech_platform_username,
            password=settings.tech_platform_password,
            system_id=settings.tech_platform_system_id,
            verify_ssl=settings.tech_platform_verify_ssl,
        )

    async def _project_module(
        self,
        db: AsyncSession,
        project_id: str,
        module_id: str,
        current_user: object,
    ) -> TechPlatformDeploymentModule:
        await project_service.get_project(db, project_id, current_user)
        module = await db.get(TechPlatformDeploymentModule, module_id)
        if module is None or str(module.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="技术中台部署模块不存在")
        return module

    async def _project_site(
        self,
        db: AsyncSession,
        project_id: str,
        public_site_id: str,
        current_user: object,
    ) -> Site:
        await project_service.get_project(db, project_id, current_user)
        site = await site_service.get_site_by_public_id(
            db, public_site_id, current_user
        )
        if str(site.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="项目仓库不存在")
        return site

    async def serialize_module(
        self,
        db: AsyncSession,
        module: TechPlatformDeploymentModule,
        site: Site | None = None,
    ) -> dict[str, Any]:
        site = site or await db.get(Site, module.site_id)
        return {
            "id": str(module.id),
            "project_id": str(module.project_id),
            "site_id": site.site_id if site else "",
            "site_name": site.name if site else "",
            "dockerfile_path": module.dockerfile_path,
            "build_context": module.build_context,
            "app_name": module.app_name,
            "namespace": module.namespace,
            "harbor_project": module.harbor_project,
            "repository_name": module.repository_name,
            "app_type": module.app_type,
            "container_port": module.container_port,
            "service_port": module.service_port,
            "config_map_template": module.config_map_template,
            "deployment_template": module.deployment_template,
            "service_template": module.service_template,
            "platform_app_id": module.platform_app_id,
            "is_available": module.is_available,
            "last_task_id": module.last_task_id or "",
            "last_image": module.last_image,
            "last_commit_sha": module.last_commit_sha,
            "status": module.status,
            "last_error": module.last_error,
            "last_deployed_at": (
                module.last_deployed_at.isoformat() if module.last_deployed_at else None
            ),
            "created_at": module.created_at.isoformat() if module.created_at else None,
            "updated_at": module.updated_at.isoformat() if module.updated_at else None,
        }

    async def list_modules(
        self,
        db: AsyncSession,
        project_id: str,
        current_user: object,
    ) -> list[dict[str, Any]]:
        await project_service.get_project(db, project_id, current_user)
        rows = await db.execute(
            select(TechPlatformDeploymentModule)
            .where(TechPlatformDeploymentModule.project_id == project_id)
            .order_by(TechPlatformDeploymentModule.created_at.asc())
        )
        modules = list(rows.scalars().all())
        site_ids = {str(item.site_id) for item in modules}
        site_map: dict[str, Site] = {}
        if site_ids:
            site_rows = await db.execute(select(Site).where(Site.id.in_(site_ids)))
            site_map = {str(site.id): site for site in site_rows.scalars().all()}
        return [
            await self.serialize_module(db, item, site_map.get(str(item.site_id)))
            for item in modules
        ]

    async def scan_modules(
        self,
        db: AsyncSession,
        project_id: str,
        current_user: object,
    ) -> list[dict[str, Any]]:
        await project_service.get_project(db, project_id, current_user)
        repos = await project_service.get_project_repos(db, project_id)
        existing_rows = await db.execute(
            select(TechPlatformDeploymentModule).where(
                TechPlatformDeploymentModule.project_id == project_id
            )
        )
        existing = list(existing_rows.scalars().all())
        existing_by_key = {
            (str(item.site_id), item.dockerfile_path): item for item in existing
        }
        found: set[tuple[str, str]] = set()
        settings = get_settings()

        for site in repos:
            repo_root = project_service.repo_root(project_id, site.name)
            if not repo_root.is_dir():
                continue
            for path in repo_root.rglob("Dockerfile*"):
                relative = path.relative_to(repo_root)
                if (
                    any(part in IGNORED_SCAN_DIRS for part in relative.parts)
                    or not path.is_file()
                ):
                    continue
                if path.name != "Dockerfile" and not path.name.startswith(
                    "Dockerfile."
                ):
                    continue
                resolved = path.resolve(strict=False)
                resolved_root = repo_root.resolve()
                if resolved != resolved_root and resolved_root not in resolved.parents:
                    continue
                rel_path = relative.as_posix()
                key = (str(site.id), rel_path)
                found.add(key)
                current = existing_by_key.get(key)
                if current is not None:
                    current.is_available = True
                    continue
                module_name = self.default_module_name(site, rel_path)
                context = relative.parent.as_posix()
                module = TechPlatformDeploymentModule(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    site_id=str(site.id),
                    dockerfile_path=rel_path,
                    build_context=context if context not in {"", "."} else ".",
                    app_name=module_name,
                    namespace=settings.tech_platform_namespace,
                    harbor_project=settings.harbor_project,
                    repository_name=module_name,
                    app_type="2",
                    container_port=8080,
                    service_port=80,
                    **self.default_templates(),
                )
                db.add(module)
                existing_by_key[key] = module
        for item in existing:
            if (str(item.site_id), item.dockerfile_path) not in found:
                item.is_available = False
        await db.commit()
        return await self.list_modules(db, project_id, current_user)

    async def create_module(
        self,
        db: AsyncSession,
        project_id: str,
        payload: TechPlatformModuleCreate,
        current_user: object,
    ) -> dict[str, Any]:
        site = await self._project_site(db, project_id, payload.site_id, current_user)
        dockerfile_path = self.normalize_relative_path(
            payload.dockerfile_path, field="Dockerfile"
        )
        build_context = self.normalize_relative_path(
            payload.build_context
            or PurePosixPath(dockerfile_path).parent.as_posix()
            or ".",
            field="构建上下文",
        )
        repo_root = project_service.repo_root(project_id, site.name)
        self.resolve_repo_path(
            repo_root, dockerfile_path, field="Dockerfile", kind="file"
        )
        self.resolve_repo_path(repo_root, build_context, field="构建上下文", kind="dir")
        defaults = self.default_templates()
        name = self.default_module_name(site, dockerfile_path)
        settings = get_settings()
        module = TechPlatformDeploymentModule(
            id=str(uuid.uuid4()),
            project_id=project_id,
            site_id=str(site.id),
            dockerfile_path=dockerfile_path,
            build_context=build_context,
            app_name=payload.app_name or name,
            namespace=payload.namespace or settings.tech_platform_namespace,
            harbor_project=payload.harbor_project or settings.harbor_project,
            repository_name=payload.repository_name or name,
            app_type=payload.app_type,
            container_port=payload.container_port,
            service_port=payload.service_port,
            config_map_template=payload.config_map_template
            or defaults["config_map_template"],
            deployment_template=payload.deployment_template
            or defaults["deployment_template"],
            service_template=payload.service_template or defaults["service_template"],
        )
        self.render_templates(
            module, image="registry.example.invalid/project/image:preview"
        )
        db.add(module)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=409, detail="该仓库的 Dockerfile 已配置部署模块"
            ) from exc
        await db.refresh(module)
        return await self.serialize_module(db, module, site)

    async def update_module(
        self,
        db: AsyncSession,
        project_id: str,
        module_id: str,
        payload: TechPlatformModuleUpdate,
        current_user: object,
    ) -> dict[str, Any]:
        module = await self._project_module(db, project_id, module_id, current_user)
        site = await db.get(Site, module.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="模块所属仓库不存在")
        values = payload.model_dump(exclude_unset=True)
        if any(value is None for value in values.values()):
            raise HTTPException(status_code=422, detail="部署模块字段不能设置为空")
        dockerfile_path = self.normalize_relative_path(
            str(values.get("dockerfile_path", module.dockerfile_path)),
            field="Dockerfile",
        )
        build_context = self.normalize_relative_path(
            str(values.get("build_context", module.build_context)), field="构建上下文"
        )
        repo_root = project_service.repo_root(project_id, site.name)
        self.resolve_repo_path(
            repo_root, dockerfile_path, field="Dockerfile", kind="file"
        )
        self.resolve_repo_path(repo_root, build_context, field="构建上下文", kind="dir")
        for field, value in values.items():
            setattr(module, field, value)
        module.dockerfile_path = dockerfile_path
        module.build_context = build_context
        module.is_available = True
        self.render_templates(
            module, image="registry.example.invalid/project/image:preview"
        )
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=409, detail="该仓库的 Dockerfile 已配置部署模块"
            ) from exc
        await db.refresh(module)
        return await self.serialize_module(db, module, site)

    async def delete_module(
        self,
        db: AsyncSession,
        project_id: str,
        module_id: str,
        current_user: object,
    ) -> None:
        module = await self._project_module(db, project_id, module_id, current_user)
        if module.last_task_id:
            task = await db.get(Task, module.last_task_id)
            if task and task.status in {
                TaskStatus.QUEUED.value,
                TaskStatus.RUNNING.value,
            }:
                raise HTTPException(
                    status_code=409, detail="部署任务执行中，不能删除模块"
                )
        await db.delete(module)
        await db.commit()

    async def preview_module(
        self,
        db: AsyncSession,
        project_id: str,
        module_id: str,
        current_user: object,
        image: str = "",
    ) -> dict[str, Any]:
        module = await self._project_module(db, project_id, module_id, current_user)
        settings = get_settings()
        preview_image = image.strip() or (
            f"{settings.harbor_registry}/{module.harbor_project}/{module.repository_name}:preview"
        )
        return {
            "image": preview_image,
            "resources": self.render_templates(module, image=preview_image),
        }

    async def validate_module(
        self,
        db: AsyncSession,
        project_id: str,
        module_id: str,
        current_user: object,
        image: str = "",
    ) -> dict[str, Any]:
        module = await self._project_module(db, project_id, module_id, current_user)
        if not module.platform_app_id:
            raise HTTPException(
                status_code=409, detail="模块尚未同步到技术中台，请先执行一次部署"
            )
        preview = await self.preview_module(
            db, project_id, module_id, current_user, image
        )
        try:
            async with self.client() as client:
                await client.login()
                types = required_resource_types(
                    await client.get_yaml_resource_types(), RESOURCE_ORDER
                )
                results = []
                for resource in preview["resources"]:
                    response = await client.check_yaml(
                        app_id=module.platform_app_id,
                        kind=resource["kind"],
                        resource_type=types[resource["kind"]],
                        yaml_text=resource["yaml"],
                    )
                    results.append(
                        {"kind": resource["kind"], "ok": True, "response": response}
                    )
        except TechPlatformError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {**preview, "valid": True, "checks": results}

    async def create_deploy_task(
        self,
        db: AsyncSession,
        project_id: str,
        module_id: str,
        current_user: object,
    ) -> Task:
        module = await self._project_module(db, project_id, module_id, current_user)
        site = await db.get(Site, module.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="模块所属仓库不存在")
        if not module.is_available:
            raise HTTPException(
                status_code=409, detail="Dockerfile 已不存在，请修复路径或删除模块"
            )
        repo_root = project_service.repo_root(project_id, site.name)
        self.resolve_repo_path(
            repo_root, module.dockerfile_path, field="Dockerfile", kind="file"
        )
        self.resolve_repo_path(
            repo_root, module.build_context, field="构建上下文", kind="dir"
        )
        if module.last_task_id:
            previous = await db.get(Task, module.last_task_id)
            if previous and previous.status in {
                TaskStatus.QUEUED.value,
                TaskStatus.RUNNING.value,
            }:
                raise HTTPException(
                    status_code=409, detail="该模块已有部署任务正在执行"
                )

        image_tag = datetime.now().strftime("t%Y%m%d.%H%M")
        settings = get_settings()
        image = (
            f"{settings.harbor_registry}/{module.harbor_project}/"
            f"{module.repository_name}:{image_tag}"
        )
        snapshot = {
            "module_id": str(module.id),
            "project_id": str(module.project_id),
            "site_id": str(module.site_id),
            "site_public_id": site.site_id,
            "site_name": site.name,
            "main_branch": site.main_branch,
            "dockerfile_path": module.dockerfile_path,
            "build_context": module.build_context,
            "app_name": module.app_name,
            "namespace": module.namespace,
            "harbor_project": module.harbor_project,
            "repository_name": module.repository_name,
            "app_type": module.app_type,
            "container_port": module.container_port,
            "service_port": module.service_port,
            "config_map_template": module.config_map_template,
            "deployment_template": module.deployment_template,
            "service_template": module.service_template,
            "platform_app_id": module.platform_app_id,
            "image_tag": image_tag,
            "image": image,
            "harbor_registry": settings.harbor_registry,
            "docker_build_platform": settings.docker_build_platform,
        }
        self.render_templates(
            snapshot, image="registry.example.invalid/project/image:preview"
        )
        task = Task(
            id=str(uuid.uuid4()),
            site_id=str(site.id),
            project_id=project_id,
            title=f"部署 {module.app_name} 到技术中台",
            description=f"{site.name}/{module.dockerfile_path}",
            provider="",
            task_type="deploy_tech_platform",
            status=TaskStatus.QUEUED.value,
            payload_json={"module_id": str(module.id), "snapshot": snapshot},
        )
        db.add(task)
        await db.flush()
        module.last_task_id = str(task.id)
        module.status = "queued"
        module.last_error = ""
        await db.commit()
        await db.refresh(task)
        await task_service.append_log(
            db, task, "技术中台部署任务已创建", source="deploy"
        )
        try:
            task_service.enqueue_task(task, raise_on_error=True)
        except Exception as exc:
            message = f"部署任务入队失败: {exc}"
            module.status = "failed"
            module.last_error = message[:2000]
            await db.commit()
            await task_service.update_status(
                db, task, TaskStatus.FAILED, error=message[:2000]
            )
            await task_service.append_log(db, task, message, "ERROR", source="deploy")
            raise HTTPException(status_code=503, detail="部署任务入队失败") from exc
        return task

    @staticmethod
    def git_head(repo_root: Path) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("无法读取仓库 Commit")
        return result.stdout.strip()


tech_platform_deploy_service = TechPlatformDeployService()
