from datetime import datetime

from pydantic import BaseModel


class VersionCreateRequest(BaseModel):
    site_id: str
    commit_message: str


class VersionResponse(BaseModel):
    id: str
    site_id: str
    version_number: int
    snapshot_url: str
    commit_message: str
    created_at: datetime | None = None

