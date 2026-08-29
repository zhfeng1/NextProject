from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import pytest


async def _create_empty_project_with_repos(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    names: tuple[str, ...],
) -> tuple[str, dict[str, str]]:
    response = await client.post(
        "/api/v2/projects",
        json={"name": "Tech Platform Project", "create_default_repo": False},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    project_id = response.json()["project"]["id"]
    repo_ids: dict[str, str] = {}
    for name in names:
        response = await client.post(
            f"/api/v2/projects/{project_id}/repos",
            json={"name": name, "starter": "empty"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        repo_ids[name] = response.json()["repo"]["site_id"]
    return project_id, repo_ids


@pytest.mark.asyncio
async def test_scan_multiple_repositories_is_idempotent_and_marks_missing_files(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module: Any,
) -> None:
    project_id, _ = await _create_empty_project_with_repos(
        client, auth_headers, ("api-repo", "worker-repo")
    )
    from backend.services.project_service import project_service

    api_root = project_service.repo_root(project_id, "api-repo")
    worker_root = project_service.repo_root(project_id, "worker-repo")
    (api_root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (api_root / "Dockerfile.worker").write_text("FROM scratch\n", encoding="utf-8")
    (worker_root / "jobs").mkdir()
    (worker_root / "jobs" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (worker_root / "node_modules").mkdir()
    (worker_root / "node_modules" / "Dockerfile.hidden").write_text(
        "FROM scratch\n", encoding="utf-8"
    )

    response = await client.post(
        f"/api/v2/projects/{project_id}/tech-platform/modules/scan",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    modules = response.json()["modules"]
    assert {(item["site_name"], item["dockerfile_path"]) for item in modules} == {
        ("api-repo", "Dockerfile"),
        ("api-repo", "Dockerfile.worker"),
        ("worker-repo", "jobs/Dockerfile"),
    }
    assert all(item["namespace"] == "" for item in modules)
    worker_module = next(
        item for item in modules if item["dockerfile_path"] == "Dockerfile.worker"
    )
    assert worker_module["build_context"] == "."

    response = await client.patch(
        f"/api/v2/projects/{project_id}/tech-platform/modules/{worker_module['id']}",
        json={"app_name": "custom-worker", "container_port": 9090},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    response = await client.post(
        f"/api/v2/projects/{project_id}/tech-platform/modules/scan",
        headers=auth_headers,
    )
    modules = response.json()["modules"]
    worker_module = next(item for item in modules if item["id"] == worker_module["id"])
    assert worker_module["app_name"] == "custom-worker"
    assert worker_module["container_port"] == 9090

    (api_root / "Dockerfile.worker").unlink()
    response = await client.post(
        f"/api/v2/projects/{project_id}/tech-platform/modules/scan",
        headers=auth_headers,
    )
    worker_module = next(
        item for item in response.json()["modules"] if item["id"] == worker_module["id"]
    )
    assert worker_module["is_available"] is False

    safe_module = next(
        item
        for item in response.json()["modules"]
        if item["site_name"] == "api-repo" and item["dockerfile_path"] == "Dockerfile"
    )
    duplicate = await client.post(
        f"/api/v2/projects/{project_id}/tech-platform/modules",
        json={"site_id": safe_module["site_id"], "dockerfile_path": "Dockerfile"},
        headers=auth_headers,
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_module_paths_reject_traversal_absolute_and_symlink_escape(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module: Any,
    tmp_path: Path,
) -> None:
    project_id, repo_ids = await _create_empty_project_with_repos(
        client, auth_headers, ("secure-repo",)
    )
    from backend.services.project_service import project_service

    repo_root = project_service.repo_root(project_id, "secure-repo")
    (repo_root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    outside_file = tmp_path / "Dockerfile.outside"
    outside_file.write_text("FROM scratch\n", encoding="utf-8")
    outside_context = tmp_path / "outside-context"
    outside_context.mkdir()
    os.symlink(outside_file, repo_root / "Dockerfile.escape")
    os.symlink(outside_context, repo_root / "escape-context")

    scan = await client.post(
        f"/api/v2/projects/{project_id}/tech-platform/modules/scan",
        headers=auth_headers,
    )
    assert scan.status_code == 200, scan.text
    assert [item["dockerfile_path"] for item in scan.json()["modules"]] == [
        "Dockerfile"
    ]

    for dockerfile_path in ("../Dockerfile", str(outside_file), "Dockerfile.escape"):
        response = await client.post(
            f"/api/v2/projects/{project_id}/tech-platform/modules",
            json={
                "site_id": repo_ids["secure-repo"],
                "dockerfile_path": dockerfile_path,
            },
            headers=auth_headers,
        )
        assert response.status_code == 400, response.text

    response = await client.post(
        f"/api/v2/projects/{project_id}/tech-platform/modules",
        json={
            "site_id": repo_ids["secure-repo"],
            "dockerfile_path": "Dockerfile",
            "build_context": "escape-context",
        },
        headers=auth_headers,
    )
    assert response.status_code == 400, response.text


def test_strict_template_rendering_and_default_yaml() -> None:
    from fastapi import HTTPException
    import yaml

    from backend.services.tech_platform_deploy_service import (
        tech_platform_deploy_service,
    )

    module = {
        "app_name": "demo-app",
        "namespace": "ocean-km",
        "harbor_project": "demo",
        "repository_name": "demo-app",
        "container_port": 8080,
        "service_port": 80,
        **tech_platform_deploy_service.default_templates(),
    }
    image = "harbor.example/demo/demo-app:t20260829.1200"
    resources = tech_platform_deploy_service.render_templates(module, image=image)
    assert [item["kind"] for item in resources] == [
        "ConfigMap",
        "Deployment",
        "Service",
    ]
    parsed = {item["kind"]: yaml.safe_load(item["yaml"]) for item in resources}
    assert (
        parsed["Deployment"]["spec"]["template"]["spec"]["containers"][0]["image"]
        == image
    )
    assert parsed["Service"]["spec"]["ports"][0] == {
        "name": "http",
        "port": 80,
        "targetPort": 8080,
    }

    invalid_variable = {
        **module,
        "config_map_template": "kind: ConfigMap\ndata: {{ missing }}\n",
    }
    with pytest.raises(HTTPException, match="模板渲染失败"):
        tech_platform_deploy_service.render_templates(invalid_variable, image=image)

    invalid_yaml = {**module, "service_template": "kind: Service\nmetadata: [\n"}
    with pytest.raises(HTTPException, match="YAML 无效"):
        tech_platform_deploy_service.render_templates(invalid_yaml, image=image)

    wrong_kind = {**module, "deployment_template": "apiVersion: v1\nkind: Service\n"}
    with pytest.raises(HTTPException, match="kind 必须为 Deployment"):
        tech_platform_deploy_service.render_templates(wrong_kind, image=image)


@pytest.mark.asyncio
async def test_platform_client_create_update_dynamic_types_and_check_error() -> None:
    from backend.services.tech_platform_client import (
        TechPlatformClient,
        TechPlatformError,
    )

    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/apollo/user/login":
            return httpx.Response(
                200,
                json={"code": "00000", "result": {"token": "token-one"}},
                headers={"set-cookie": "SESSION=session-one; Path=/"},
            )
        assert request.headers["System-Id"] == "system-one"
        assert request.headers["X-User-Token"] == "token-one"
        assert "SESSION=session-one" in request.headers.get("cookie", "")
        if request.url.path == "/devops/cicd/v1.0/job/saveAll":
            return httpx.Response(
                200, json={"code": "00000", "result": {"data": [270]}}
            )
        if request.url.path == "/devops/cicd/v1.0/job/270/saveAll":
            return httpx.Response(200, json={"code": "00000", "result": {}})
        if request.url.path == "/devops/cicd/v1.0/job/yaml/template":
            return httpx.Response(
                200,
                json={
                    "code": "00000",
                    "result": [
                        {"kind": "ConfigMap", "resourceType": 9},
                        {"k8sKind": "Deployment", "resource_type": "4"},
                        {"resourceKind": "Service", "value": 7},
                    ],
                },
            )
        if request.url.path == "/devops/cicd/k8s/yaml/checkYaml":
            return httpx.Response(
                200,
                json={
                    "code": "00000",
                    "result": {"errorType": 2, "message": "invalid yaml"},
                },
            )
        raise AssertionError(request.url.path)

    platform = TechPlatformClient(
        base_url="http://platform.test",
        username="encrypted-user",
        password="encrypted-password",
        system_id="system-one",
    )
    await platform.client.aclose()
    platform.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await platform.login()
        app_id, _ = await platform.save_application(
            app_id="",
            app_name="demo",
            harbor_project="ocean-km",
            repository_name="demo",
            image_tag="t20260829.1200",
            app_type="2",
        )
        assert app_id == "270"
        updated_id, _ = await platform.save_application(
            app_id=app_id,
            app_name="demo",
            harbor_project="ocean-km",
            repository_name="demo",
            image_tag="t20260829.1201",
            app_type="2",
        )
        assert updated_id == "270"
        assert await platform.get_yaml_resource_types() == {
            "configmap": 9,
            "deployment": 4,
            "service": 7,
        }
        with pytest.raises(TechPlatformError, match="errorType=2"):
            await platform.check_yaml(
                app_id="270",
                kind="ConfigMap",
                resource_type=9,
                yaml_text="kind: ConfigMap\n",
            )
    finally:
        await platform.aclose()

    assert ("POST", "/devops/cicd/v1.0/job/saveAll") in calls
    assert ("POST", "/devops/cicd/v1.0/job/270/saveAll") in calls


@pytest.mark.asyncio
async def test_platform_client_reauthenticates_once_after_session_expiry() -> None:
    from backend.services.tech_platform_client import TechPlatformClient

    login_count = 0
    template_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_count, template_count
        if request.url.path == "/apollo/user/login":
            login_count += 1
            return httpx.Response(
                200,
                json={"code": "00000", "token": f"token-{login_count}"},
                headers={"set-cookie": f"SESSION=session-{login_count}; Path=/"},
            )
        if request.url.path == "/devops/cicd/v1.0/job/yaml/template":
            template_count += 1
            if template_count == 1:
                assert request.headers["X-User-Token"] == "token-1"
                return httpx.Response(401, json={"message": "expired"})
            assert request.headers["X-User-Token"] == "token-2"
            assert "SESSION=session-2" in request.headers.get("cookie", "")
            return httpx.Response(200, json={"code": "00000", "data": []})
        raise AssertionError(request.url.path)

    platform = TechPlatformClient(
        base_url="http://platform.test",
        username="encrypted-user",
        password="encrypted-password",
        system_id="system-one",
    )
    await platform.client.aclose()
    platform.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await platform.login()
        assert await platform.get_yaml_resource_types() == {}
    finally:
        await platform.aclose()
    assert login_count == 2
    assert template_count == 2


@pytest.mark.asyncio
async def test_validation_gate_and_deploy_order_record_partial_failure() -> None:
    from backend.services.tech_platform_deploy_service import (
        TechPlatformResourceError,
        validate_and_deploy_resources,
    )

    resources = [
        {"kind": kind, "yaml": f"kind: {kind}\n"}
        for kind in ("ConfigMap", "Deployment", "Service")
    ]
    resource_types = {"ConfigMap": 9, "Deployment": 4, "Service": 7}

    class FakeClient:
        def __init__(self, *, fail_check: str = "", fail_deploy: str = "") -> None:
            self.fail_check = fail_check
            self.fail_deploy = fail_deploy
            self.calls: list[tuple[str, str]] = []

        async def check_yaml(self, **kwargs: Any) -> dict[str, Any]:
            kind = kwargs["kind"]
            self.calls.append(("check", kind))
            if kind == self.fail_check:
                raise RuntimeError("check rejected")
            return {}

        async def deploy_yaml(self, **kwargs: Any) -> dict[str, Any]:
            kind = kwargs["kind"]
            self.calls.append(("deploy", kind))
            if kind == self.fail_deploy:
                raise RuntimeError("deploy rejected")
            return {}

    failed_check = FakeClient(fail_check="Deployment")
    with pytest.raises(TechPlatformResourceError) as check_error:
        await validate_and_deploy_resources(
            failed_check,
            app_id="270",
            resources=resources,
            resource_types=resource_types,
        )
    assert check_error.value.phase == "validate"
    assert check_error.value.kind == "Deployment"
    assert failed_check.calls == [("check", "ConfigMap"), ("check", "Deployment")]

    successful = FakeClient()
    assert await validate_and_deploy_resources(
        successful, app_id="270", resources=resources, resource_types=resource_types
    ) == ["ConfigMap", "Deployment", "Service"]
    assert successful.calls == [
        ("check", "ConfigMap"),
        ("check", "Deployment"),
        ("check", "Service"),
        ("deploy", "ConfigMap"),
        ("deploy", "Deployment"),
        ("deploy", "Service"),
    ]

    partial = FakeClient(fail_deploy="Service")
    with pytest.raises(TechPlatformResourceError) as deploy_error:
        await validate_and_deploy_resources(
            partial, app_id="270", resources=resources, resource_types=resource_types
        )
    assert deploy_error.value.phase == "deploy"
    assert deploy_error.value.kind == "Service"
    assert deploy_error.value.deployed_resources == ["ConfigMap", "Deployment"]


@pytest.mark.asyncio
async def test_deploy_api_freezes_non_secret_snapshot_and_blocks_concurrent_task(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await client.post(
        "/api/v2/projects",
        json={"name": "Deploy Snapshot Project"},
        headers=auth_headers,
    )
    project = response.json()["project"]
    scan = await client.post(
        f"/api/v2/projects/{project['id']}/tech-platform/modules/scan",
        headers=auth_headers,
    )
    module = scan.json()["modules"][0]

    preview = await client.post(
        f"/api/v2/projects/{project['id']}/tech-platform/modules/{module['id']}/preview",
        json={},
        headers=auth_headers,
    )
    assert preview.status_code == 409

    configured = await client.patch(
        f"/api/v2/projects/{project['id']}/tech-platform/modules/{module['id']}",
        json={"namespace": "ocean-km"},
        headers=auth_headers,
    )
    assert configured.status_code == 200, configured.text
    module = configured.json()["module"]

    from backend.models import Task
    from backend.services.task_service import task_service

    monkeypatch.setattr(task_service, "enqueue_task", lambda *_args, **_kwargs: True)
    deploy = await client.post(
        f"/api/v2/projects/{project['id']}/tech-platform/modules/{module['id']}/deploy",
        headers=auth_headers,
    )
    assert deploy.status_code == 200, deploy.text
    task_id = deploy.json()["task_id"]
    async with app_module.AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        assert task is not None
        snapshot = task.payload_json["snapshot"]
        assert snapshot["image"].endswith(
            f"/{module['repository_name']}:{snapshot['image_tag']}"
        )
        assert snapshot["harbor_registry"] == "harbor.trscd.com.cn"
        assert snapshot["docker_build_platform"] == "linux/amd64"
        serialized = str(snapshot).lower()
        assert "password" not in serialized
        assert "username" not in serialized
        assert "token" not in serialized

    concurrent = await client.post(
        f"/api/v2/projects/{project['id']}/tech-platform/modules/{module['id']}/deploy",
        headers=auth_headers,
    )
    assert concurrent.status_code == 409

    delete = await client.delete(
        f"/api/v2/projects/{project['id']}/tech-platform/modules/{module['id']}",
        headers=auth_headers,
    )
    assert delete.status_code == 409


def test_sensitive_deploy_log_content_is_redacted() -> None:
    from backend.services.execution_trace_service import redact_execution_text

    redacted = redact_execution_text(
        "token=secret-token password=secret-password "
        "https://user:secret@git.example/repo.git?access_token=query-secret"
    )
    assert "secret-token" not in redacted
    assert "secret-password" not in redacted
    assert "user:secret" not in redacted
    assert "query-secret" not in redacted
    assert "[REDACTED]" in redacted
