from __future__ import annotations

import httpx
import pytest


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
async def test_login_success(client: httpx.AsyncClient) -> None:
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
