from __future__ import annotations

import importlib
import shutil
import subprocess
import uuid

import httpx
import pytest
from sqlalchemy import select


def git(repo, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


async def create_site(client: httpx.AsyncClient, auth_headers: dict[str, str], site_id: str) -> None:
    response = await client.post(
        "/api/v2/sites",
        json={"site_id": site_id, "name": site_id, "auto_start": False},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_git_snapshots_and_rollback_create_auditable_versions(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    await create_site(client, auth_headers, "versioned-site")
    site_root = app_module.site_service.site_root("versioned-site")
    index_file = site_root / "frontend" / "index.html"
    original_index = index_file.read_text(encoding="utf-8")

    first = await client.post(
        "/api/v2/versions/sites/versioned-site/snapshot",
        json={"commit_message": "Version one"},
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    first_version = first.json()["version"]
    assert first_version["version_number"] == 1
    assert len(first_version["commit_sha"]) == 40
    assert "snapshot_url" not in first_version
    assert git(site_root, "rev-list", "-n", "1", "nextproject/version/v1") == first_version["commit_sha"]

    index_file.write_text("<h1>version two</h1>\n", encoding="utf-8")
    added_file = site_root / "frontend" / "added-in-v2.txt"
    added_file.write_text("new file\n", encoding="utf-8")
    second = await client.post(
        "/api/v2/versions/sites/versioned-site/snapshot",
        json={"commit_message": "Version two"},
        headers=auth_headers,
    )
    assert second.status_code == 200, second.text
    second_version = second.json()["version"]
    assert second_version["version_number"] == 2
    assert second_version["diff_summary"]["files_changed"] >= 2

    rollback = await client.post(
        "/api/v2/versions/sites/versioned-site/rollback",
        json={"version_number": 1},
        headers=auth_headers,
    )
    assert rollback.status_code == 200, rollback.text
    payload = rollback.json()
    rolled_back = payload["version"]
    assert rolled_back["version_number"] == 3
    assert rolled_back["diff_summary"]["operation"] == "rollback"
    assert payload["restored_from"]["version_number"] == 1
    assert index_file.read_text(encoding="utf-8") == original_index
    assert not added_file.exists()
    assert git(site_root, "rev-list", "-n", "1", "nextproject/version/v3") == rolled_back["commit_sha"]
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", second_version["commit_sha"], rolled_back["commit_sha"]],
        cwd=site_root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "cat-file", "-e", f"{second_version['commit_sha']}^{{commit}}"],
        cwd=site_root,
        capture_output=True,
        check=True,
    )

    listed = await client.get("/api/v2/versions/sites/versioned-site", headers=auth_headers)
    assert [item["version_number"] for item in listed.json()["versions"]] == [3, 2, 1]


@pytest.mark.asyncio
async def test_snapshot_allows_empty_body_and_empty_commit(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    await create_site(client, auth_headers, "empty-snapshot-site")
    response = await client.post(
        "/api/v2/versions/sites/empty-snapshot-site/snapshot",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"]["commit_message"] == "Manual snapshot"
    assert response.json()["version"]["diff_summary"]["files_changed"] == 0


@pytest.mark.asyncio
async def test_rollback_rejects_dirty_worktree(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    await create_site(client, auth_headers, "dirty-version-site")
    snapshot = await client.post(
        "/api/v2/versions/sites/dirty-version-site/snapshot",
        json={"commit_message": "clean"},
        headers=auth_headers,
    )
    assert snapshot.status_code == 200
    site_root = app_module.site_service.site_root("dirty-version-site")
    (site_root / "untracked.txt").write_text("do not lose\n", encoding="utf-8")

    response = await client.post(
        "/api/v2/versions/sites/dirty-version-site/rollback",
        json={"version_number": 1},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert (site_root / "untracked.txt").exists()


@pytest.mark.asyncio
async def test_snapshot_initializes_legacy_standalone_site_repository(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    await create_site(client, auth_headers, "legacy-version-site")
    site_root = app_module.site_service.site_root("legacy-version-site")
    shutil.rmtree(site_root / ".git")

    response = await client.post(
        "/api/v2/versions/sites/legacy-version-site/snapshot",
        json={"commit_message": "Import legacy site"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert (site_root / ".git").is_dir()
    assert git(site_root, "branch", "--show-current") == "main"


@pytest.mark.asyncio
async def test_snapshot_rejects_active_site_task(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    await create_site(client, auth_headers, "busy-version-site")
    models = importlib.import_module("backend.models")
    async with app_module.AsyncSessionLocal() as db:
        site = (await db.execute(select(models.Site).where(models.Site.site_id == "busy-version-site"))).scalar_one()
        db.add(
            models.AgentTask(
                id=str(uuid.uuid4()),
                site_id=site.id,
                task_type="develop_code",
                status=models.TaskStatus.RUNNING.value,
            )
        )
        await db.commit()

    response = await client.post(
        "/api/v2/versions/sites/busy-version-site/snapshot",
        json={"commit_message": "must wait"},
        headers=auth_headers,
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_template_creation_uses_builtin_starter_without_archive(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    templates = await client.get("/api/v2/templates")
    assert templates.status_code == 200
    template = templates.json()["templates"][0]
    assert "code_archive_url" not in template

    created = await client.post(
        "/api/v2/templates/sites/from-template",
        json={"template_id": template["id"], "site_name": "Template Git Site"},
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    site_root = app_module.site_service.site_root(created.json()["site_id"])
    assert (site_root / ".git").is_dir()
    assert (site_root / "backend" / "app.py").exists()


@pytest.mark.asyncio
async def test_health_payload_has_no_minio_component(app_module) -> None:
    payload = await app_module.build_health_payload()
    assert "minio" not in payload["components"]
