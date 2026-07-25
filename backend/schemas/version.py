from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class VersionSnapshotRequest(BaseModel):
    commit_message: str = Field(default="Manual snapshot", max_length=500)

    @field_validator("commit_message")
    @classmethod
    def normalize_commit_message(cls, value: str) -> str:
        return value.strip() or "Manual snapshot"


class VersionRollbackRequest(BaseModel):
    version_number: int = Field(gt=0)


class VersionResponse(BaseModel):
    id: str
    site_id: str
    version_number: int
    commit_sha: str
    commit_message: str
    created_at: datetime | None = None
