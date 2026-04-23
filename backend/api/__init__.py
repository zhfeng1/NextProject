from fastapi import APIRouter

from backend.api.v1 import sites as v1_sites
from backend.api.v1 import tasks as v1_tasks
from backend.api.v2 import auth, conversations, deploy, mcp, projects, providers, sites, skills, stats, tasks, templates, versions, websocket, workflows


def build_api_router() -> APIRouter:
    router = APIRouter()
    router.include_router(v1_sites.router, prefix="/api/v1", tags=["V1 Sites"])
    router.include_router(v1_tasks.router, prefix="/api/v1", tags=["V1 Tasks"])
    router.include_router(auth.router, prefix="/api/v2", tags=["Auth"])
    router.include_router(conversations.router, prefix="/api/v2", tags=["Conversations"])
    router.include_router(projects.router, prefix="/api/v2", tags=["Projects"])
    router.include_router(sites.router, prefix="/api/v2", tags=["Sites"])
    router.include_router(tasks.router, prefix="/api/v2", tags=["Tasks"])
    router.include_router(templates.router, prefix="/api/v2", tags=["Templates"])
    router.include_router(versions.router, prefix="/api/v2", tags=["Versions"])
    router.include_router(stats.router, prefix="/api/v2", tags=["Stats"])
    router.include_router(deploy.router, prefix="/api/v2", tags=["Deploy"])
    router.include_router(providers.router, prefix="/api/v2", tags=["Providers"])
    router.include_router(mcp.router, prefix="/api/v2", tags=["MCP"])
    router.include_router(skills.router, prefix="/api/v2", tags=["Skills"])
    router.include_router(workflows.router, prefix="/api/v2", tags=["Workflows"])
    router.include_router(websocket.router)
    return router


api_router = build_api_router()

__all__ = ["api_router", "build_api_router"]
