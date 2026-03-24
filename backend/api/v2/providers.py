from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.models.user_llm_provider import UserLLMProvider

router = APIRouter(prefix="/providers")


def _serialize(p: UserLLMProvider) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "name": p.name,
        "base_url": p.base_url,
        "api_key": p.api_key,
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
        api_key=(payload.get("api_key") or "").strip(),
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
        if key in allowed:
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


@router.post("/fetch-models")
async def fetch_models(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
) -> dict[str, Any]:
    base_url = (payload.get("base_url") or "").strip().rstrip("/")
    api_key = (payload.get("api_key") or "").strip()
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
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
