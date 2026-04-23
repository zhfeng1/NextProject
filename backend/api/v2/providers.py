from __future__ import annotations

import ipaddress
import socket
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.core.encryption import decrypt_api_key, encrypt_api_key, is_masked, mask_api_key
from backend.models.user_llm_provider import UserLLMProvider

router = APIRouter(prefix="/providers")

# ---------------------------------------------------------------------------
# SSRF protection: block requests to internal / private networks
# ---------------------------------------------------------------------------
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_url_ssrf(url: str) -> None:
    """Raise HTTPException if *url* targets a private / internal address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="base_url must use http or https protocol")
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="base_url has no valid hostname")
    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail=f"Cannot resolve hostname: {hostname}")
    for _family, _type, _proto, _canonname, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        for net in _BLOCKED_NETWORKS:
            if ip in net:
                raise HTTPException(
                    status_code=400,
                    detail="base_url must not point to internal/private network addresses",
                )


def _serialize(p: UserLLMProvider) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "name": p.name,
        "base_url": p.base_url,
        "api_key": mask_api_key(decrypt_api_key(p.api_key)) if p.api_key else "",
        "models": p.models or [],
        "format": p.format,
        "is_default": bool(p.is_default),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("")
async def list_providers(
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user_id = str(getattr(current_user, "id"))
    rows = await db.execute(
        select(UserLLMProvider).where(UserLLMProvider.user_id == user_id).order_by(UserLLMProvider.created_at)
    )
    return {"ok": True, "providers": [_serialize(p) for p in rows.scalars().all()]}


@router.post("")
async def create_provider(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user_id = str(getattr(current_user, "id"))
    p = UserLLMProvider(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=(payload.get("name") or "").strip() or "New Provider",
        base_url=(payload.get("base_url") or "").strip(),
        api_key=encrypt_api_key((payload.get("api_key") or "").strip()),
        models=payload.get("models") or [],
        format=payload.get("format") or "responses",
        is_default=bool(payload.get("is_default", False)),
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return {"ok": True, "provider": _serialize(p)}


@router.put("/{provider_id}")
async def update_provider(
    provider_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user_id = str(getattr(current_user, "id"))
    p = await db.get(UserLLMProvider, provider_id)
    if p is None or str(p.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Provider not found")
    allowed = {"name", "base_url", "api_key", "models", "format", "is_default"}
    for key, value in payload.items():
        if key not in allowed:
            continue
        if key == "api_key":
            raw_key = (value or "").strip()
            if not raw_key or is_masked(raw_key):
                continue  # skip masked or empty api_key — user didn't change it
            setattr(p, key, encrypt_api_key(raw_key))
        else:
            setattr(p, key, value)
    await db.commit()
    await db.refresh(p)
    return {"ok": True, "provider": _serialize(p)}


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user_id = str(getattr(current_user, "id"))
    p = await db.get(UserLLMProvider, provider_id)
    if p is None or str(p.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Provider not found")
    await db.delete(p)
    await db.commit()
    return {"ok": True}


@router.post("/verify-model")
async def verify_model(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider_id = (payload.get("provider_id") or "").strip()
    model = (payload.get("model") or "").strip()
    if not provider_id or not model:
        raise HTTPException(status_code=400, detail="provider_id and model are required")

    user_id = str(getattr(current_user, "id"))
    p = await db.get(UserLLMProvider, provider_id)
    if p is None or str(p.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Provider not found")

    base_url = (p.base_url or "").strip().rstrip("/")

    # SSRF mitigation: block private/internal networks
    if base_url:
        _validate_url_ssrf(base_url)

    # Resolve API key: prefer raw api_key from payload, fall back to DB
    api_key = (payload.get("api_key") or "").strip()
    if not api_key:
        api_key = decrypt_api_key(p.api_key) if p.api_key else ""
    if not api_key:
        return {"ok": False, "error": "API Key 为空，请先输入并保存 Key"}
    fmt = p.format or "responses"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if fmt == "messages":
                # Claude API
                resp = await client.post(
                    f"{base_url}/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 5,
                    },
                )
            elif fmt == "responses":
                # OpenAI Responses API
                resp = await client.post(
                    f"{base_url}/responses",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "input": "hi",
                        "max_output_tokens": 5,
                    },
                )
            else:
                # OpenAI Chat Completions API (fallback)
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 5,
                    },
                )
            resp.raise_for_status()
            return {"ok": True, "message": f"模型 {model} 连通正常"}
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("error", {}).get("message", str(exc))
        except Exception:
            detail = exc.response.text[:200]
        return {"ok": False, "error": f"{exc.response.status_code}: {detail}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/fetch-models")
async def fetch_models(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    base_url = (payload.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")

    # SSRF mitigation: block private/internal networks
    _validate_url_ssrf(base_url)

    # Resolve API key: prefer raw api_key (user just typed it) over provider_id (DB)
    # This ensures a newly entered key is tested immediately, even before saving.
    api_key = (payload.get("api_key") or "").strip()
    if not api_key:
        provider_id = (payload.get("provider_id") or "").strip()
        if provider_id:
            user_id = str(getattr(current_user, "id"))
            p = await db.get(UserLLMProvider, provider_id)
            if p is not None and str(p.user_id) == user_id and p.api_key:
                api_key = decrypt_api_key(p.api_key)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            )
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data") or data.get("models") or []
            model_ids = sorted([m["id"] if isinstance(m, dict) else str(m) for m in models])
            return {"ok": True, "models": model_ids}
    except Exception as exc:
        return {"ok": False, "models": [], "error": str(exc)}
