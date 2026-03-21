from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Organization, OrganizationMember, User
from backend.models.user_config import UserConfig
from backend.utils.validation import slugify

from backend.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
)


class AuthService:
    def serialize_user(self, user: object) -> dict[str, Any]:
        return {
            "id": str(getattr(user, "id")),
            "email": getattr(user, "email", ""),
            "name": getattr(user, "name", None),
            "avatar_url": getattr(user, "avatar_url", None),
            "is_superuser": bool(getattr(user, "is_superuser", False)),
            "default_org_id": str(getattr(user, "default_org_id", "")) if getattr(user, "default_org_id", None) else None,
        }

    def serialize_user_config(self, cfg: UserConfig) -> dict[str, Any]:
        return {
            "llm_mode": cfg.llm_mode,
            "llm_base_url": cfg.llm_base_url,
            "llm_api_key": cfg.llm_api_key,
            "llm_model": cfg.llm_model,
            "codex_client_id": cfg.codex_client_id,
            "codex_client_secret": cfg.codex_client_secret,
            "codex_redirect_uri": cfg.codex_redirect_uri,
            "codex_access_token": cfg.codex_access_token,
            "codex_mcp_url": cfg.codex_mcp_url,
            "claude_api_key": cfg.claude_api_key,
            "gemini_api_key": cfg.gemini_api_key,
        }

    async def _get_or_create_user_config(self, db: AsyncSession, user_id: str) -> UserConfig:
        cfg = await db.get(UserConfig, user_id)
        if cfg is None:
            cfg = UserConfig(user_id=user_id)
            db.add(cfg)
            await db.flush()
        return cfg

    async def register_user(self, db: AsyncSession, email: str, password: str, name: str | None) -> dict[str, Any]:
        if not email or not password:
            raise HTTPException(status_code=400, detail="email and password are required")
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            password_hash=get_password_hash(password),
            name=name,
            is_active=True,
            is_superuser=False,
        )
        org_name = f"{name or email.split('@')[0]}'s Organization"
        org = Organization(
            id=str(uuid.uuid4()),
            name=org_name,
            slug=f"{slugify(org_name)}-{uuid.uuid4().hex[:6]}",
        )
        member = OrganizationMember(org_id=str(org.id), user_id=str(user.id), role="owner")
        db.add_all([user, org, member])
        await db.flush()
        if hasattr(user, "default_org_id"):
            user.default_org_id = org.id
        await db.commit()
        return {"user_id": str(user.id), "organization_id": str(org.id)}

    async def login(self, db: AsyncSession, email: str, password: str) -> dict[str, Any]:
        row = await db.execute(select(User).where(User.email == email))
        user = row.scalar_one_or_none()
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Incorrect email or password")
        access_token = create_access_token({"sub": str(user.id)})
        refresh_token = create_refresh_token({"sub": str(user.id)})
        return {
            "ok": True,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": self.serialize_user(user),
        }

    async def refresh_access_token(self, db: AsyncSession, refresh_token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
            if payload.get("type") != "refresh":
                raise HTTPException(status_code=401, detail="Invalid token type")
            user_id = payload.get("sub")
        except JWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid refresh token") from exc
        user = await db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        access_token = create_access_token({"sub": str(user.id)})
        return {
            "ok": True,
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def update_profile(self, db: AsyncSession, user: User, name: str | None, avatar_url: str | None) -> dict[str, Any]:
        if name is not None:
            user.name = name or None
        if avatar_url is not None:
            user.avatar_url = avatar_url or None
        await db.commit()
        return {"ok": True, "user": self.serialize_user(user)}

    async def update_email(self, db: AsyncSession, user: User, new_email: str, current_password: str) -> dict[str, Any]:
        if not new_email:
            raise HTTPException(status_code=400, detail="new_email is required")
        if not verify_password(current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Incorrect password")
        existing = await db.execute(select(User).where(User.email == new_email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = new_email
        await db.commit()
        return {"ok": True, "user": self.serialize_user(user)}

    async def update_password(self, db: AsyncSession, user: User, current_password: str, new_password: str) -> dict[str, Any]:
        if not current_password or not new_password:
            raise HTTPException(status_code=400, detail="current_password and new_password are required")
        if not verify_password(current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Incorrect current password")
        if len(new_password) < 6:
            raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
        user.password_hash = get_password_hash(new_password)
        await db.commit()
        return {"ok": True}

    async def get_user_config(self, db: AsyncSession, user_id: str) -> dict[str, Any]:
        cfg = await self._get_or_create_user_config(db, user_id)
        await db.commit()
        return {"ok": True, "config": self.serialize_user_config(cfg)}

    async def update_user_config(self, db: AsyncSession, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        cfg = await self._get_or_create_user_config(db, user_id)
        allowed = {
            "llm_mode", "llm_base_url", "llm_api_key", "llm_model",
            "codex_client_id", "codex_client_secret", "codex_redirect_uri",
            "codex_access_token", "codex_mcp_url",
            "claude_api_key", "gemini_api_key",
        }
        for key, value in data.items():
            if key in allowed:
                setattr(cfg, key, value)
        await db.commit()
        return {"ok": True, "config": self.serialize_user_config(cfg)}


auth_service = AuthService()
