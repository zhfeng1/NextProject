from __future__ import annotations

import importlib
import sys
from pathlib import Path

import httpx
import pytest
from prometheus_client import REGISTRY


def _clear_backend_modules() -> None:
    for name in list(sys.modules):
        if name == "backend" or name.startswith("backend."):
            sys.modules.pop(name, None)


def _reset_prometheus_registry() -> None:
    for collector in list(REGISTRY._collector_to_names):
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            continue


@pytest.fixture
async def app_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.db"
    shared_dir = tmp_path / "shared"
    generated_sites_root = tmp_path / "generated_sites"
    shared_dir.mkdir(parents=True, exist_ok=True)
    generated_sites_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("SYNC_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/15")
    monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_SECRET_KEY", "minioadmin2025")
    monkeypatch.setenv("MINIO_SECURE", "false")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-at-least-32-characters")
    monkeypatch.setenv("GENERATED_SITES_ROOT", str(generated_sites_root))
    monkeypatch.setenv("PLAYWRIGHT_BASE_URL", "http://test")
    monkeypatch.setenv("APP_ENV", "test")

    _clear_backend_modules()
    _reset_prometheus_registry()
    backend_main = importlib.import_module("backend.main")
    await backend_main.ensure_bootstrap_data()
    return backend_main


@pytest.fixture
async def client(app_module):
    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    email = "tester@example.com"
    password = "TesterPass123"
    await client.post(
        "/api/v2/auth/register",
        json={"email": email, "password": password, "name": "Tester"},
    )
    response = await client.post(
        "/api/v2/auth/login",
        json={"email": email, "password": password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
