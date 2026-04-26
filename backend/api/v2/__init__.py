from backend.api.v2.auth import router as auth_router
from backend.api.v2.conversations import router as conversations_router
from backend.api.v2.deploy import router as deploy_router
from backend.api.v2.mcp import router as mcp_router
from backend.api.v2.skills import router as skills_router
from backend.api.v2.sites import router as sites_router
from backend.api.v2.tasks import router as tasks_router
from backend.api.v2.templates import router as templates_router
from backend.api.v2.versions import router as versions_router
from backend.api.v2.websocket import router as websocket_router
from backend.api.v2.workflows import router as workflows_router

__all__ = [
    "auth_router",
    "conversations_router",
    "deploy_router",
    "mcp_router",
    "sites_router",
    "skills_router",
    "tasks_router",
    "templates_router",
    "versions_router",
    "websocket_router",
    "workflows_router",
]
