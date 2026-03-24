from __future__ import annotations

from typing import AsyncGenerator, Callable

from fastapi import HTTPException


try:
    from backend.core.database import get_db as _get_db
except Exception:  # pragma: no cover - temporary during incremental migration.
    _get_db = None


try:
    from backend.core.security import get_current_user as _get_current_user
except Exception:  # pragma: no cover - temporary during incremental migration.
    _get_current_user = None


async def get_db() -> AsyncGenerator[object, None]:
    if _get_db is None:
        raise HTTPException(status_code=503, detail="Database dependency is not ready")
    async for session in _get_db():
        yield session


if _get_current_user is not None:
    get_current_user = _get_current_user
else:

    async def get_current_user() -> object:
        raise HTTPException(status_code=503, detail="Security dependency is not ready")


async def get_current_superuser(current_user: object = None) -> object:
    if current_user is None:
        current_user = await get_current_user()
    if not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Superuser privileges required")
    return current_user


def require_site_access() -> Callable[[object], object]:
    async def _checker(current_user: object = None) -> object:
        return current_user or await get_current_user()

    return _checker
