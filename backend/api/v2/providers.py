from __future__ import annotations

import ipaddress
import socket
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.core.encryption import decrypt_api_key, encrypt_api_key, is_masked, mask_api_key
from backend.models.user_llm_provider import UserLLMProvider
from backend.services.programming_tool_service import SUPPORTED_FORMATS, programming_tool_service
from backend.services.project_service import project_service

router = APIRouter(prefix="/providers")
SUPPORTED_FORMATS_SET = set(SUPPORTED_FORMATS)

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
        raise HTTPException(status_code=400, detail="base_url 必须使用 http 或 https 协议")
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="base_url 主机名无效")
    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail=f"无法解析主机名: {hostname}")
    for _family, _type, _proto, _canonname, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        for net in _BLOCKED_NETWORKS:
            if ip in net:
                raise HTTPException(
                    status_code=400,
                    detail="base_url 不允许指向内网或私有网络地址",
                )


def _serialize(p: UserLLMProvider) -> dict[str, Any]:
    formats = _provider_formats(p)
    enabled_formats = _provider_enabled_formats(p)
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "scope_type": getattr(p, "scope_type", "") or "global",
        "project_id": str(p.project_id) if getattr(p, "project_id", None) else "",
        "name": p.name,
        "base_url": p.base_url,
        "api_key": mask_api_key(decrypt_api_key(p.api_key)) if p.api_key else "",
        "models": p.models or [],
        "format": formats[0],
        "formats": formats,
        "enabled_formats": enabled_formats,
        "is_default": bool(p.is_default),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _provider_formats(provider: UserLLMProvider) -> list[str]:
    return programming_tool_service.provider_formats(provider)


def _provider_enabled_formats(provider: UserLLMProvider) -> list[str]:
    return programming_tool_service.provider_enabled_formats(provider)


def _normalize_formats(payload: dict[str, Any], existing: UserLLMProvider | None = None) -> list[str]:
    raw = payload.get("formats")
    if raw is None:
        raw = payload.get("format")
    if raw is None and existing is not None:
        raw = _provider_formats(existing)
    if raw is None:
        raw = ["responses"]
    if isinstance(raw, str):
        raw = [raw]
    requested = [str(item).strip() for item in raw if str(item).strip()]
    if any(fmt not in SUPPORTED_FORMATS_SET for fmt in requested):
        raise HTTPException(
            status_code=400,
            detail="formats only supports responses, messages, or chat_completions",
        )
    formats = requested
    formats = list(dict.fromkeys(formats))
    if not formats:
        raise HTTPException(
            status_code=400,
            detail="formats must include responses, messages, or chat_completions",
        )
    return formats


def _normalize_enabled_formats(
    payload: dict[str, Any],
    formats: list[str],
    *,
    existing: UserLLMProvider | None = None,
) -> list[str]:
    if "enabled_formats" in payload:
        raw = payload.get("enabled_formats")
    elif existing is not None:
        raw = [fmt for fmt in _provider_enabled_formats(existing) if fmt in formats]
    else:
        # Backwards compatibility: older clients only send formats. A newly
        # created provider remains immediately usable for those formats.
        raw = formats
    if raw is None:
        raw = []
    if isinstance(raw, str):
        raw = [raw]
    enabled = list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))
    invalid = [fmt for fmt in enabled if fmt not in formats or fmt not in SUPPORTED_FORMATS_SET]
    if invalid:
        raise HTTPException(status_code=400, detail="enabled_formats must be a subset of formats")
    return enabled


async def _claim_enabled_formats(
    db: AsyncSession,
    provider: UserLLMProvider,
    enabled_formats: list[str],
) -> None:
    """Make each enabled format unique inside a user/scope/project."""
    provider.enabled_formats_json = enabled_formats
    if not enabled_formats:
        return
    query = select(UserLLMProvider).where(
        UserLLMProvider.user_id == str(provider.user_id),
        UserLLMProvider.scope_type == provider.scope_type,
        UserLLMProvider.id != str(provider.id),
    )
    if provider.scope_type == "project":
        query = query.where(UserLLMProvider.project_id == provider.project_id)
    else:
        query = query.where(UserLLMProvider.project_id.is_(None))
    rows = await db.execute(query.with_for_update())
    claimed = set(enabled_formats)
    for other in rows.scalars().all():
        current = _provider_enabled_formats(other)
        remaining = [fmt for fmt in current if fmt not in claimed]
        if remaining != current:
            other.enabled_formats_json = remaining


async def _normalize_scope(
    db: AsyncSession,
    current_user: object,
    payload: dict[str, Any],
    *,
    existing: UserLLMProvider | None = None,
) -> tuple[str, str | None]:
    scope_type = str(payload.get("scope_type") or getattr(existing, "scope_type", "") or "global").strip() or "global"
    if scope_type not in {"global", "project"}:
        raise HTTPException(status_code=400, detail="scope_type must be global or project")
    project_id = str(payload.get("project_id") or getattr(existing, "project_id", "") or "").strip() or None
    if scope_type == "global":
        return "global", None
    if not project_id:
        raise HTTPException(status_code=400, detail="project scope requires project_id")
    await project_service.get_project(db, project_id, current_user)
    return "project", project_id


@router.get("")
async def list_providers(
    format: str | None = Query(default=None),
    scope_type: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user_id = str(getattr(current_user, "id"))
    query = select(UserLLMProvider).where(UserLLMProvider.user_id == user_id)
    if scope_type:
        query = query.where(UserLLMProvider.scope_type == scope_type)
    if project_id:
        await project_service.get_project(db, project_id, current_user)
        query = query.where(
            or_(
                UserLLMProvider.scope_type == "global",
                UserLLMProvider.project_id == project_id,
            )
        )
    rows = await db.execute(query.order_by(UserLLMProvider.scope_type, UserLLMProvider.created_at))
    providers = list(rows.scalars().all())
    if format:
        providers = [p for p in providers if format in _provider_formats(p)]
    return {"ok": True, "providers": [_serialize(p) for p in providers]}


@router.post("")
async def create_provider(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user_id = str(getattr(current_user, "id"))
    scope_type, project_id = await _normalize_scope(db, current_user, payload)
    formats = _normalize_formats(payload)
    enabled_formats = _normalize_enabled_formats(payload, formats)
    p = UserLLMProvider(
        id=str(uuid.uuid4()),
        user_id=user_id,
        scope_type=scope_type,
        project_id=project_id,
        name=(payload.get("name") or "").strip() or "New Provider",
        base_url=(payload.get("base_url") or "").strip(),
        api_key=encrypt_api_key((payload.get("api_key") or "").strip()),
        models=payload.get("models") or [],
        format=formats[0],
        formats_json=formats,
        enabled_formats_json=enabled_formats,
        is_default=bool(payload.get("is_default", False)),
    )
    db.add(p)
    await db.flush()
    await _claim_enabled_formats(db, p, enabled_formats)
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
        raise HTTPException(status_code=404, detail="Provider 未找到")
    if "scope_type" in payload or "project_id" in payload:
        p.scope_type, p.project_id = await _normalize_scope(db, current_user, payload, existing=p)
    formats = _normalize_formats(payload, existing=p)
    enabled_formats = _normalize_enabled_formats(payload, formats, existing=p)
    enabled_formats = [fmt for fmt in enabled_formats if fmt in formats]
    if "format" in payload or "formats" in payload:
        p.format = formats[0]
        p.formats_json = formats
    allowed = {"name", "base_url", "api_key", "models", "is_default"}
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
    await _claim_enabled_formats(db, p, enabled_formats)
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
        raise HTTPException(status_code=404, detail="Provider 未找到")
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
        raise HTTPException(status_code=400, detail="provider_id 和 model 为必填项")

    user_id = str(getattr(current_user, "id"))
    p = await db.get(UserLLMProvider, provider_id)
    if p is None or str(p.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Provider 未找到")

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
    fmt = str(payload.get("format") or "").strip()
    provider_formats = _provider_formats(p)
    if not fmt:
        fmt = provider_formats[0]
    if fmt not in provider_formats:
        raise HTTPException(status_code=400, detail=f"Provider 不支持 {fmt} 格式")

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
        raise HTTPException(status_code=400, detail="base_url 为必填项")

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
