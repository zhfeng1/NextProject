from __future__ import annotations

import os
import subprocess
import uuid

import httpx
import pytest


@pytest.mark.asyncio
async def test_create_site(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/v2/sites",
        json={"site_id": "test-site", "name": "Test Site", "auto_start": False},
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["site"]["site_id"] == "test-site"
    assert payload["site"]["status"] == "stopped"


@pytest.mark.asyncio
async def test_create_site_generates_uuid_site_id(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v2/sites",
        json={"name": "UUID Site", "auto_start": False},
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    generated_site_id = payload["site"]["site_id"]
    assert str(uuid.UUID(generated_site_id)) == generated_site_id


@pytest.mark.asyncio
async def test_create_site_creates_docs_directory(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    response = await client.post(
        "/api/v2/sites",
        json={"site_id": "docs-site", "name": "Docs Site", "auto_start": False},
        headers=auth_headers,
    )

    assert response.status_code == 200
    site_root = app_module.site_service.site_root("docs-site")
    assert (site_root / "docs").is_dir()
    assert (site_root / "docs" / "README.md").exists()


@pytest.mark.asyncio
async def test_list_sites_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v2/sites")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_sites_returns_created_site(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    await client.post(
        "/api/v2/sites",
        json={"site_id": "list-site", "name": "List Site", "auto_start": False},
        headers=auth_headers,
    )

    response = await client.get("/api/v2/sites", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert any(site["site_id"] == "list-site" for site in payload["sites"])


@pytest.mark.asyncio
async def test_requirements_are_saved_under_docs(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    await client.post(
        "/api/v2/sites",
        json={"site_id": "req-site", "name": "Req Site", "auto_start": False},
        headers=auth_headers,
    )

    write_response = await client.post(
        "/api/v2/sites/req-site/requirements",
        json={"content": "整理首页和支付模块需求"},
        headers=auth_headers,
    )

    assert write_response.status_code == 200
    site_root = app_module.site_service.site_root("req-site")
    requirements_file = app_module.site_service.requirements_file("req-site")
    assert requirements_file == site_root / "docs" / "requirements.md"
    assert requirements_file.exists()
    assert "整理首页和支付模块需求" in requirements_file.read_text(encoding="utf-8")
    assert not (site_root / "REQUIREMENTS.md").exists()


@pytest.mark.asyncio
async def test_site_file_browser_lists_and_reads_files(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    await client.post(
        "/api/v2/sites",
        json={"site_id": "browse-site", "name": "Browse Site", "auto_start": False},
        headers=auth_headers,
    )

    list_response = await client.get("/api/v2/sites/browse-site/files", headers=auth_headers)
    assert list_response.status_code == 200
    entries = list_response.json()["entries"]
    assert any(item["path"] == "frontend" and item["type"] == "directory" for item in entries)
    assert any(item["path"] == "backend" and item["type"] == "directory" for item in entries)

    file_response = await client.get(
        "/api/v2/sites/browse-site/file",
        params={"path": "frontend/index.html"},
        headers=auth_headers,
    )
    assert file_response.status_code == 200
    payload = file_response.json()
    assert payload["path"] == "frontend/index.html"
    assert "<!doctype html>" in payload["content"]
    assert payload["binary"] is False


@pytest.mark.asyncio
async def test_site_file_browser_blocks_path_escape(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    await client.post(
        "/api/v2/sites",
        json={"site_id": "safe-site", "name": "Safe Site", "auto_start": False},
        headers=auth_headers,
    )

    response = await client.get(
        "/api/v2/sites/safe-site/file",
        params={"path": "../outside.txt"},
        headers=auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_site_from_git_repository(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
    tmp_path,
) -> None:
    source_repo = tmp_path / "source-repo"
    (source_repo / "frontend").mkdir(parents=True)
    (source_repo / "backend").mkdir(parents=True)
    (source_repo / "frontend" / "index.html").write_text("<h1>from git</h1>", encoding="utf-8")
    (source_repo / "backend" / "app.py").write_text("print('from git')\n", encoding="utf-8")

    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init"], cwd=source_repo, check=True, capture_output=True, env=git_env)
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True, capture_output=True, env=git_env)
    subprocess.run(["git", "commit", "-m", "init"], cwd=source_repo, check=True, capture_output=True, env=git_env)

    response = await client.post(
        "/api/v2/sites",
        json={"site_id": "git-site", "name": "Git Site", "git_url": str(source_repo)},
        headers=auth_headers,
    )

    assert response.status_code == 200
    site_root = app_module.site_service.site_root("git-site")
    assert (site_root / ".git").exists()
    assert (site_root / "frontend" / "index.html").read_text(encoding="utf-8") == "<h1>from git</h1>"
    assert (site_root / "docs" / "README.md").exists()
    assert response.json()["site"]["config"]["git_source"]["branch"] == ""


@pytest.mark.asyncio
async def test_create_site_from_git_repository_branch(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
    tmp_path,
) -> None:
    source_repo = tmp_path / "branch-source-repo"
    (source_repo / "frontend").mkdir(parents=True)
    (source_repo / "backend").mkdir(parents=True)
    (source_repo / "frontend" / "index.html").write_text("<h1>main branch</h1>", encoding="utf-8")
    (source_repo / "backend" / "app.py").write_text("print('main')\n", encoding="utf-8")

    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init"], cwd=source_repo, check=True, capture_output=True, env=git_env)
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True, capture_output=True, env=git_env)
    subprocess.run(["git", "commit", "-m", "main"], cwd=source_repo, check=True, capture_output=True, env=git_env)
    subprocess.run(["git", "checkout", "-b", "feature/demo"], cwd=source_repo, check=True, capture_output=True, env=git_env)
    (source_repo / "frontend" / "index.html").write_text("<h1>feature branch</h1>", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True, capture_output=True, env=git_env)
    subprocess.run(["git", "commit", "-m", "feature"], cwd=source_repo, check=True, capture_output=True, env=git_env)

    response = await client.post(
        "/api/v2/sites",
        json={
            "site_id": "git-branch-site",
            "name": "Git Branch Site",
            "git_url": str(source_repo),
            "git_branch": "feature/demo",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    site_root = app_module.site_service.site_root("git-branch-site")
    assert (site_root / "frontend" / "index.html").read_text(encoding="utf-8") == "<h1>feature branch</h1>"
    assert payload["site"]["config"]["git_source"]["branch"] == "feature/demo"


@pytest.mark.asyncio
async def test_create_site_from_git_repository_persists_start_command(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    tmp_path,
) -> None:
    source_repo = tmp_path / "command-source-repo"
    (source_repo / "frontend").mkdir(parents=True)
    (source_repo / "backend").mkdir(parents=True)
    (source_repo / "frontend" / "index.html").write_text("<h1>command</h1>", encoding="utf-8")
    (source_repo / "backend" / "app.py").write_text("print('command')\n", encoding="utf-8")

    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init"], cwd=source_repo, check=True, capture_output=True, env=git_env)
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True, capture_output=True, env=git_env)
    subprocess.run(["git", "commit", "-m", "init"], cwd=source_repo, check=True, capture_output=True, env=git_env)

    response = await client.post(
        "/api/v2/sites",
        json={
            "site_id": "git-command-site",
            "name": "Git Command Site",
            "git_url": str(source_repo),
            "start_command": "pnpm dev --host 0.0.0.0 --port $PORT",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["site"]["config"]["start_command"] == "pnpm dev --host 0.0.0.0 --port $PORT"
