from __future__ import annotations

import httpx
import pytest
from jose import jwt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/providers/codex/auth/status"),
        ("POST", "/api/providers/codex/auth/start"),
        ("GET", "/api/codex/oauth/status"),
        ("POST", "/api/codex/oauth/start"),
        ("GET", "/api/claude-code/auth/status"),
        ("POST", "/api/claude-code/auth/start"),
    ],
)
async def test_programming_tool_auth_compatibility_routes_require_login(
    client: httpx.AsyncClient,
    method: str,
    path: str,
) -> None:
    response = await client.request(method, path)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_register_success(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v2/auth/register",
        json={"email": "alice@example.com", "password": "AlicePass123", "name": "Alice"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["user_id"]
    assert payload["organization_id"]


@pytest.mark.asyncio
async def test_register_duplicate_email(client: httpx.AsyncClient) -> None:
    payload = {"email": "dup@example.com", "password": "DupPass123", "name": "Dup"}

    first = await client.post("/api/v2/auth/register", json=payload)
    second = await client.post("/api/v2/auth/register", json=payload)

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == "Email already registered"


@pytest.mark.asyncio
async def test_login_success(client: httpx.AsyncClient, app_module) -> None:
    await client.post(
        "/api/v2/auth/register",
        json={"email": "login@example.com", "password": "LoginPass123", "name": "Login"},
    )

    response = await client.post(
        "/api/v2/auth/login",
        json={"email": "login@example.com", "password": "LoginPass123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["refresh_token"]

    settings = app_module.settings
    access_payload = jwt.decode(payload["access_token"], settings.secret_key, algorithms=[settings.jwt_algorithm])
    refresh_payload = jwt.decode(payload["refresh_token"], settings.secret_key, algorithms=[settings.jwt_algorithm])
    assert access_payload["sid"]
    assert access_payload["sid"] == refresh_payload["sid"]


@pytest.mark.asyncio
async def test_logout_revokes_redis_backed_session(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v2/auth/register",
        json={"email": "logout@example.com", "password": "LogoutPass123", "name": "Logout"},
    )
    login = await client.post(
        "/api/v2/auth/login",
        json={"email": "logout@example.com", "password": "LogoutPass123"},
    )
    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    before_logout = await client.get("/api/v2/auth/me", headers=headers)
    assert before_logout.status_code == 200

    logout = await client.post(
        "/api/v2/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert logout.status_code == 200
    assert logout.json()["ok"] is True

    after_logout = await client.get("/api/v2/auth/me", headers=headers)
    assert after_logout.status_code == 401

    refresh = await client.post(
        "/api/v2/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh.status_code == 401
    assert refresh.json()["detail"] == "Login session has expired"


@pytest.mark.asyncio
async def test_refresh_keeps_same_login_session(client: httpx.AsyncClient, app_module) -> None:
    await client.post(
        "/api/v2/auth/register",
        json={"email": "refresh@example.com", "password": "RefreshPass123", "name": "Refresh"},
    )
    login = await client.post(
        "/api/v2/auth/login",
        json={"email": "refresh@example.com", "password": "RefreshPass123"},
    )
    tokens = login.json()
    refreshed = await client.post(
        "/api/v2/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200

    settings = app_module.settings
    original_payload = jwt.decode(tokens["access_token"], settings.secret_key, algorithms=[settings.jwt_algorithm])
    refreshed_payload = jwt.decode(refreshed.json()["access_token"], settings.secret_key, algorithms=[settings.jwt_algorithm])
    assert refreshed_payload["sid"] == original_payload["sid"]
