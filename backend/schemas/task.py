from datetime import datetime

from pydantic import BaseModel


class TaskCreateRequest(BaseModel):
    site_id: str
    task_type: str
    provider: str = "codex"
    prompt: str = ""
    instruction: str = ""
    command: str = ""
    base_url: str = ""
    deploy_target: str = "local"


class TaskResponse(BaseModel):
    id: str
    site_id: str
    provider: str
    task_type: str
    status: str
    error: str = ""
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskLogResponse(BaseModel):
    id: int
    task_id: str
    ts: datetime
    level: str
    line: str

