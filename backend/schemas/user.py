from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str | None = None
    avatar_url: str | None = None
    is_active: bool
    is_superuser: bool
    default_org_id: UUID | None = None
    created_at: datetime
