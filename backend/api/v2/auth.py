from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.services.auth_service import auth_service

router = APIRouter(prefix="/auth")


@router.post("/register")
async def register(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await auth_service.register_user(
        db,
        email=(payload.get("email") or "").strip(),
        password=(payload.get("password") or "").strip(),
        name=(payload.get("name") or "").strip() or None,
    )
    return {"ok": True, **result}


@router.post("/login")
async def login(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await auth_service.login(
        db,
        email=(payload.get("email") or "").strip(),
        password=(payload.get("password") or "").strip(),
    )


@router.post("/refresh")
async def refresh_token(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    refresh_token = (payload.get("refresh_token") or "").strip()
    return await auth_service.refresh_access_token(db, refresh_token)


@router.get("/me")
async def me(current_user: object = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "user": auth_service.serialize_user(current_user)}


@router.put("/me")
async def update_profile(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await auth_service.update_profile(
        db,
        user=current_user,
        name=payload.get("name"),
        avatar_url=payload.get("avatar_url"),
    )


@router.put("/me/email")
async def update_email(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await auth_service.update_email(
        db,
        user=current_user,
        new_email=(payload.get("new_email") or "").strip(),
        current_password=(payload.get("current_password") or "").strip(),
    )


@router.put("/me/password")
async def update_password(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await auth_service.update_password(
        db,
        user=current_user,
        current_password=(payload.get("current_password") or "").strip(),
        new_password=(payload.get("new_password") or "").strip(),
    )


@router.get("/me/config")
async def get_user_config(
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await auth_service.get_user_config(db, str(getattr(current_user, "id")))


@router.put("/me/config")
async def update_user_config(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await auth_service.update_user_config(db, str(getattr(current_user, "id")), payload)
