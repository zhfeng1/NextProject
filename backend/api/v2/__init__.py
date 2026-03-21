from backend.api.v2.auth import router as auth_router
from backend.api.v2.deploy import router as deploy_router
from backend.api.v2.sites import router as sites_router
from backend.api.v2.tasks import router as tasks_router
from backend.api.v2.templates import router as templates_router
from backend.api.v2.versions import router as versions_router
from backend.api.v2.websocket import router as websocket_router

__all__ = [
    "auth_router",
    "deploy_router",
    "sites_router",
    "tasks_router",
    "templates_router",
    "versions_router",
    "websocket_router",
]
