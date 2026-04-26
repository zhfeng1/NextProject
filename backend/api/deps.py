from __future__ import annotations

from typing import AsyncGenerator, Callable

from fastapi import HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


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


def require_role(min_role: str = "viewer") -> Callable[[object, AsyncSession], object]:
    """Check if the user has the required minimum role in their default organization."""
    async def _checker(
        current_user: object = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ) -> object:
        if getattr(current_user, "is_superuser", False):
            return current_user
            
        from backend.models.organization import OrganizationMember
        from backend.models.enums import UserRole
        
        # Priority mapping: lower number = higher privilege
        role_priority = {
            UserRole.OWNER.value: 1,
            UserRole.ADMIN.value: 2,
            UserRole.DEVELOPER.value: 3,
            UserRole.VIEWER.value: 4
        }
        
        target_priority = role_priority.get(min_role, 4)
        org_id = getattr(current_user, "default_org_id", None)
        
        if not org_id:
            raise HTTPException(status_code=403, detail="User does not belong to any organization")
            
        result = await db.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.user_id == getattr(current_user, "id"),
                OrganizationMember.org_id == org_id
            )
        )
        member = result.scalar_one_or_none()
        
        if not member:
            raise HTTPException(status_code=403, detail="User is not a member of the current organization")
            
        user_priority = role_priority.get(getattr(member, "role", "viewer"), 4)
        
        if user_priority > target_priority:
            raise HTTPException(status_code=403, detail=f"Require minimum role: {min_role}")
            
        return current_user

    return _checker
