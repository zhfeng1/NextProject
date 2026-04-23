from __future__ import annotations

import enum


class SiteStatus(str, enum.Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    BUILDING = "building"
    ERROR = "error"


class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskType(str, enum.Enum):
    DEVELOP_CODE = "develop_code"
    TEST_LOCAL_PLAYWRIGHT = "test_local_playwright"
    DEPLOY_LOCAL = "deploy_local"
    DEPLOY_APOLLO = "deploy_apollo"
    CLONE_REPO = "clone_repo"


class UserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class PlanTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
