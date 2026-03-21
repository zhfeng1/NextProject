from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import subprocess
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from redis.asyncio import from_url as redis_from_url
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api import api_router
from backend.core.config import ROOT_DIR, get_settings
from backend.core.database import AsyncSessionLocal, engine, get_db
from backend.core.metrics import active_sites_total, prometheus_middleware, render_metrics
from backend.core.security import get_password_hash
from backend.models import (
    AppConfig,
    Base,
    Organization,
    OrganizationMember,
    Site,
    SiteDeployConfig,
    SiteProviderConfig,
    Template,
    User,
)
from backend.services.deploy_service import deploy_service
from backend.services.site_service import site_service
from backend.services.task_service import task_service
from backend.utils.minio import minio_client


settings = get_settings()
logger = logging.getLogger("uvicorn.error")
template_dir = ROOT_DIR / "main_service" / "app" / "templates"
if not template_dir.exists():
    template_dir = ROOT_DIR / "app" / "templates"
templates = Jinja2Templates(directory=str(template_dir))

app = FastAPI(title="NextProject Backend v2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allow_origins_list),
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=list(settings.cors_allow_methods_list),
    allow_headers=list(settings.cors_allow_headers_list),
)
app.middleware("http")(prometheus_middleware)
app.include_router(api_router)


PROVIDER_AUTH_FILES = {
    "codex": "/root/.codex/auth.json",
    "claude_code": "/root/.config/claude-code/auth.json",
    "gemini_cli": "/root/.config/gemini/auth.json",
}
provider_auth_locks = {provider: threading.Lock() for provider in settings.provider_list}
provider_auth_processes: dict[str, subprocess.Popen[str] | None] = {provider: None for provider in settings.provider_list}
provider_auth_logs: dict[str, deque[str]] = {provider: deque(maxlen=200) for provider in settings.provider_list}


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def build_llm_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["x-api-key"] = api_key
    return headers


def append_provider_auth_log(provider: str, line: str) -> None:
    provider_auth_logs[provider].append(f"[{now_iso()}] {line.rstrip()}")


async def _add_column_if_missing(conn: Any, table: str, column: str, col_def: str) -> None:
    """Idempotent column addition for SQLite and PostgreSQL."""
    dialect = conn.dialect.name
    if dialect == "postgresql":
        await conn.execute(
            text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_def}")
        )
    else:
        # SQLite: check pragma first
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        cols = [row[1] for row in result.fetchall()]
        if column not in cols:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))


async def ensure_bootstrap_data() -> None:
    async with engine.begin() as conn:
        if settings.create_tables_on_startup:
            await conn.run_sync(Base.metadata.create_all)
        # Idempotent column migrations
        await _add_column_if_missing(conn, "user_configs", "claude_api_key", "TEXT NOT NULL DEFAULT ''")
        await _add_column_if_missing(conn, "user_configs", "gemini_api_key", "TEXT NOT NULL DEFAULT ''")

    async with AsyncSessionLocal() as db:
        app_config = await db.get(AppConfig, 1)
        if app_config is None:
            db.add(AppConfig(id=1))

        result = await db.execute(select(User).where(User.email == settings.default_admin_email))
        admin = result.scalar_one_or_none()
        if admin is None:
            org = Organization(
                id=str(uuid.uuid4()),
                name=settings.default_org_name,
                slug=settings.default_org_slug,
            )
            admin = User(
                id=str(uuid.uuid4()),
                email=settings.default_admin_email,
                password_hash=get_password_hash(settings.default_admin_password),
                name="System Admin",
                is_active=True,
                is_superuser=True,
                default_org_id=org.id,
            )
            db.add_all(
                [
                    org,
                    admin,
                    OrganizationMember(org_id=org.id, user_id=admin.id, role="owner"),
                ]
            )

        template_count = (await db.execute(select(Template))).scalars().first()
        if template_count is None:
            seed_templates = [
                ("landing-starter", "营销落地页", "landing"),
                ("blog-starter", "内容博客", "blog"),
                ("dashboard-starter", "数据仪表盘", "dashboard"),
                ("shop-starter", "电商展示", "ecommerce"),
                ("portfolio-starter", "作品集", "portfolio"),
            ]
            for slug, name, category in seed_templates:
                db.add(
                    Template(
                        id=str(uuid.uuid4()),
                        slug=slug,
                        name=name,
                        category=category,
                        description=f"{name} 默认模板",
                        tech_stack={"backend": "fastapi", "frontend": "vue3"},
                        is_public=True,
                    )
                )

        await db.commit()


async def get_legacy_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.email == settings.default_admin_email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=500, detail="Default admin user is missing")
    return user


async def get_site_deploy_config(db: AsyncSession, site_id: str) -> dict[str, Any]:
    row = await db.get(SiteDeployConfig, site_id)
    defaults = {
        "site_id": site_id,
        "target_type": "local",
        "system_api_base": "http://192.168.1.15:90",
        "system_id": "",
        "app_id": "",
        "harbor_domain": "192.168.1.18",
        "harbor_domain_public": "harbor.trscd.com.cn",
        "harbor_namespace": "ocean-km",
        "module_name": site_id,
        "login_tel": "",
        "login_password": "",
        "login_random": "",
        "login_path": "/apollo/user/login",
        "deploy_path": "/devops/cicd/v1.0/job/deployByImage",
        "extra_headers_json": "{}",
    }
    if row is None:
        return defaults
    data = {key: getattr(row, key) for key in defaults}
    return {**defaults, **data}


async def save_site_deploy_config(db: AsyncSession, site_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    config = await db.get(SiteDeployConfig, site_id)
    if config is None:
        config = SiteDeployConfig(site_id=site_id)
        db.add(config)
    for key, value in payload.items():
        if hasattr(config, key) and key != "site_id":
            setattr(config, key, value)
    await db.commit()
    await db.refresh(config)
    return await get_site_deploy_config(db, site_id)


async def get_site_provider_config(db: AsyncSession, site_id: str) -> dict[str, Any]:
    row = await db.get(SiteProviderConfig, site_id)
    defaults = {
        "site_id": site_id,
        "codex_cmd": "",
        "claude_cmd": "",
        "gemini_cmd": "",
        "codex_auth_cmd": "",
        "claude_auth_cmd": "",
        "gemini_auth_cmd": "",
    }
    if row is None:
        return defaults
    data = {key: getattr(row, key) for key in defaults}
    return {**defaults, **data}


async def save_site_provider_config(db: AsyncSession, site_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    config = await db.get(SiteProviderConfig, site_id)
    if config is None:
        config = SiteProviderConfig(site_id=site_id)
        db.add(config)
    for key, value in payload.items():
        if hasattr(config, key) and key != "site_id":
            setattr(config, key, value)
    await db.commit()
    await db.refresh(config)
    return await get_site_provider_config(db, site_id)


async def get_default_site_id(db: AsyncSession, user: User) -> str:
    sites = await site_service.list_sites(db, user=user)
    return sites[0].site_id if sites else ""


async def proxy_to_sub_site(site: dict[str, Any], path: str, request: Request) -> Response:
    internal_url = (site.get("internal_url") or "").rstrip("/")
    if not internal_url:
        return JSONResponse(status_code=500, content={"ok": False, "message": "站点内部地址不可用"})

    target_path = "/" + path.lstrip("/") if path else "/"
    target_url = f"{internal_url}{target_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    filtered_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "connection"}
    }
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            upstream = await client.request(
                request.method,
                target_url,
                headers=filtered_headers,
                content=body,
            )
        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower()
            not in {
                "content-length",
                "connection",
                "keep-alive",
                "proxy-authenticate",
                "proxy-authorization",
                "te",
                "trailers",
                "transfer-encoding",
                "upgrade",
                "content-encoding",
            }
        }
        return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)
    except Exception as exc:
        return JSONResponse(status_code=502, content={"ok": False, "message": f"子网站代理失败: {exc}"})


@app.on_event("startup")
async def startup() -> None:
    from backend.services.websocket_service import websocket_manager
    asyncio.ensure_future(websocket_manager.start_redis_subscriber(settings.redis_url))
    await ensure_bootstrap_data()
    async with AsyncSessionLocal() as db:
        user = await get_legacy_user(db)
        sites = await site_service.list_sites(db, user=user)
        active_sites_total.set(sum(1 for site in sites if site.status == "running"))
        for site in sites:
            if site.status == "running":
                try:
                    await site_service.start_site(db, site.site_id, user)
                except Exception as exc:
                    logger.error("恢复站点失败: %s, err=%s", site.site_id, exc)


@app.on_event("shutdown")
async def shutdown() -> None:
    async with AsyncSessionLocal() as db:
        user = await get_legacy_user(db)
        sites = await site_service.list_sites(db, user=user)
        for site in sites:
            try:
                site_service._stop_site_process(site.site_id)
            except Exception:
                continue


@app.get("/", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("config.html", {"request": request})


@app.get("/home", response_class=HTMLResponse)
async def home_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/site-editor/{site_id}", response_class=HTMLResponse)
async def site_editor_page(request: Request, site_id: str) -> HTMLResponse:
    return templates.TemplateResponse("site_edit.html", {"request": request, "site_id": site_id})


@app.get("/site-config/{site_id}", response_class=HTMLResponse)
async def site_config_page(request: Request, site_id: str) -> HTMLResponse:
    return templates.TemplateResponse("site_config.html", {"request": request, "site_id": site_id})


@app.get("/api/config")
async def get_config(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    config = await db.get(AppConfig, 1)
    if config is None:
        return {}
    return {
        "llm_mode": config.llm_mode,
        "llm_base_url": config.llm_base_url,
        "llm_api_key": config.llm_api_key,
        "llm_model": config.llm_model,
        "codex_client_id": config.codex_client_id,
        "codex_client_secret": config.codex_client_secret,
        "codex_redirect_uri": config.codex_redirect_uri,
        "codex_access_token": config.codex_access_token,
        "codex_mcp_url": config.codex_mcp_url,
    }


@app.post("/api/config")
async def save_config(payload: dict[str, Any] = Body(default_factory=dict), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    config = await db.get(AppConfig, 1)
    if config is None:
        config = AppConfig(id=1)
        db.add(config)
    for key, value in payload.items():
        if hasattr(config, key):
            setattr(config, key, value)
    await db.commit()
    return {"ok": True}


@app.post("/api/llm-models")
async def fetch_llm_models(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    base_url = (payload.get("llm_base_url") or "https://api.openai.com/v1").rstrip("/")
    api_key = (payload.get("llm_api_key") or "").strip()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{base_url}/models", headers=build_llm_headers(api_key))
            response.raise_for_status()
        models = sorted(
            [
                item.get("id", "")
                for item in response.json().get("data", [])
                if isinstance(item, dict) and item.get("id")
            ],
            key=str.lower,
        )
        return {"ok": True, "models": models}
    except Exception as exc:
        return JSONResponse(status_code=502, content={"ok": False, "models": [], "message": str(exc)})


@app.get("/api/sites")
async def list_legacy_sites(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    sites = await site_service.list_sites(db, user=user)
    serialized = [site_service.serialize_site(site) for site in sites]
    return {"ok": True, "sites": serialized, "default_site_id": serialized[0]["site_id"] if serialized else ""}


@app.post("/api/sites")
async def create_legacy_site(payload: dict[str, Any] = Body(default_factory=dict), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    site = await site_service.create_site(
        db,
        current_user=user,
        site_id=(payload.get("site_id") or "").strip() or None,
        name=(payload.get("name") or "").strip() or None,
        auto_start=bool(payload.get("auto_start", True)),
    )
    return {"ok": True, "site": site_service.serialize_site(site)}


@app.get("/api/sites/{site_id}")
async def get_legacy_site(site_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    site = await site_service.get_site_by_public_id(db, site_id, user)
    return {
        "ok": True,
        "site": site_service.serialize_site(site),
        "data": site_service.load_site_data(site.site_id),
        "deploy_config": await get_site_deploy_config(db, site.site_id),
        "provider_config": await get_site_provider_config(db, site.site_id),
    }


@app.post("/api/sites/{site_id}/start")
async def start_legacy_site(site_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    site = await site_service.start_site(db, site_id, user)
    return {"ok": True, "site": site_service.serialize_site(site)}


@app.post("/api/sites/{site_id}/stop")
async def stop_legacy_site(site_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    site = await site_service.stop_site(db, site_id, user)
    return {"ok": True, "site": site_service.serialize_site(site)}


@app.delete("/api/sites/{site_id}")
async def delete_legacy_site(site_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    await site_service.delete_site(db, site_id, user)
    return await list_legacy_sites(db)


@app.get("/api/sites/{site_id}/deploy-config")
async def get_legacy_deploy_config(site_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {"ok": True, "site_id": site_id, "deploy_config": await get_site_deploy_config(db, site_id)}


@app.put("/api/sites/{site_id}/deploy-config")
async def put_legacy_deploy_config(
    site_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    config = await save_site_deploy_config(db, site_id, payload)
    return {"ok": True, "site_id": site_id, "deploy_config": config}


@app.get("/api/sites/{site_id}/provider-config")
async def get_legacy_provider_config(site_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {"ok": True, "site_id": site_id, "provider_config": await get_site_provider_config(db, site_id)}


@app.put("/api/sites/{site_id}/provider-config")
async def put_legacy_provider_config(
    site_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    config = await save_site_provider_config(db, site_id, payload)
    return {"ok": True, "site_id": site_id, "provider_config": config}


@app.get("/api/sites/{site_id}/tasks")
async def list_legacy_site_tasks(site_id: str, limit: int = 30, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    tasks = await task_service.list_site_tasks(db, site_id, user, limit=limit)
    return {"ok": True, "site_id": site_id, "tasks": [task_service.serialize_task(task) for task in tasks]}


@app.post("/api/sites/{site_id}/deploy")
async def deploy_legacy_site(
    site_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await get_legacy_user(db)
    target = str(payload.get("target", "local")).strip().lower()
    task = await deploy_service.create_deploy_task(db, site_id, user, target=target, options=payload)
    return {"ok": True, "task_id": str(task.id), "task_type": task.task_type, "site_id": site_id}


@app.post("/api/tasks")
async def create_legacy_task(payload: dict[str, Any] = Body(default_factory=dict), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    task = await task_service.create_task(
        db=db,
        current_user=user,
        site_id=(payload.get("site_id") or "").strip(),
        task_type=(payload.get("task_type") or "").strip(),
        provider=(payload.get("provider") or "").strip(),
        payload_data=payload,
        enqueue=True,
    )
    return {"ok": True, "task_id": str(task.id), "status": "queued", "site_id": payload.get("site_id"), "task_type": task.task_type}


@app.get("/api/tasks/{task_id}")
async def get_legacy_task(task_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    task = await task_service.get_task(db, task_id, user)
    return {"ok": True, "task": task_service.serialize_task(task)}


@app.get("/api/tasks/{task_id}/logs")
async def get_legacy_task_logs(task_id: str, after_id: int = 0, limit: int = 200, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    logs = await task_service.get_task_logs(db, task_id, user, after_id=after_id, limit=limit)
    return {"ok": True, "logs": logs, "next_after_id": logs[-1]["id"] if logs else after_id}


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_legacy_task(task_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    task = await task_service.cancel_task(db, task_id, user)
    return {"ok": True, "task_id": str(task.id)}


@app.post("/api/build-site")
async def build_site(payload: dict[str, Any] = Body(default_factory=dict), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    site_id = (payload.get("site_id") or "").strip() or await get_default_site_id(db, user)
    if not site_id:
        raise HTTPException(status_code=404, detail="暂无站点，请先创建")
    requirement = (payload.get("requirement") or "").strip()
    if not requirement:
        raise HTTPException(status_code=400, detail="requirement 不能为空")
    site = await site_service.get_site_by_public_id(db, site_id, user)
    data = site_service.load_site_data(site.site_id)
    data["requirement"] = requirement
    data.setdefault("notes", []).append(f"初始生成：{payload.get('builder', 'llm')}")
    if not data.get("title"):
        data["title"] = site.name
    site_service.save_site_data(site.site_id, data)
    await site_service.restart_site(db, site.site_id, user)
    return {"ok": True, "result": data, "site_id": site.site_id, "preview_url": site_service.preview_url_for_site(site.site_id)}


@app.post("/api/adjust-site")
async def adjust_site(payload: dict[str, Any] = Body(default_factory=dict), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    site_id = (payload.get("site_id") or "").strip() or await get_default_site_id(db, user)
    instruction = (payload.get("instruction") or "").strip()
    if not site_id:
        raise HTTPException(status_code=404, detail="暂无站点，请先创建")
    site = await site_service.apply_adjustment(db, site_id, user, instruction)
    return {"ok": True, "site_id": site.site_id, "preview_url": site_service.preview_url_for_site(site.site_id)}


@app.post("/api/test-site")
async def test_site(payload: dict[str, Any] = Body(default_factory=dict), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await get_legacy_user(db)
    site_id = (payload.get("site_id") or "").strip() or await get_default_site_id(db, user)
    if not site_id:
        return JSONResponse(status_code=404, content={"ok": False, "message": "暂无站点，请先创建"})
    config = await db.get(AppConfig, 1)
    if config is None or not config.codex_mcp_url:
        return JSONResponse(status_code=400, content={"ok": False, "message": "未配置 codex_mcp_url，无法触发 Chrome DevTools MCP。"})
    return {"ok": True, "site_id": site_id, "result": {"target": f"/sites/{site_id}", "message": "MCP 测试请求已接受"}}


@app.post("/api/providers/{provider}/auth/start")
async def provider_auth_start(
    provider: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if provider not in settings.provider_list:
        raise HTTPException(status_code=400, detail=f"provider 不支持: {provider}")
    user = await get_legacy_user(db)
    site_id = (payload.get("site_id") or "").strip() or await get_default_site_id(db, user)
    if not site_id:
        raise HTTPException(status_code=404, detail="暂无站点，请先创建")
    config = await get_site_provider_config(db, site_id)
    command_map = {
        "codex": config.get("codex_auth_cmd") or settings.codex_auth_cmd,
        "claude_code": config.get("claude_auth_cmd") or settings.claude_auth_cmd,
        "gemini_cli": config.get("gemini_auth_cmd") or settings.gemini_auth_cmd,
    }
    command = shlex.split(command_map[provider])
    with provider_auth_locks[provider]:
        existing = provider_auth_processes.get(provider)
        if existing and existing.poll() is None:
            return {"ok": True, "started": False, "message": "已有认证流程在运行中"}
        process = subprocess.Popen(
            command,
            cwd=str(site_service.site_root(site_id)),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        provider_auth_processes[provider] = process
        append_provider_auth_log(provider, f"开始认证命令: {' '.join(command)}")

    def _pump() -> None:
        if not process.stdout:
            return
        for line in process.stdout:
            append_provider_auth_log(provider, line)
        append_provider_auth_log(provider, f"认证进程退出，code={process.returncode}")

    threading.Thread(target=_pump, daemon=True).start()
    return {"ok": True, "started": True}


@app.get("/api/providers/{provider}/auth/status")
async def provider_auth_status(provider: str) -> dict[str, Any]:
    if provider not in settings.provider_list:
        raise HTTPException(status_code=400, detail=f"provider 不支持: {provider}")
    process = provider_auth_processes.get(provider)
    auth_file = Path(PROVIDER_AUTH_FILES[provider])
    return {
        "ok": True,
        "provider": provider,
        "running": bool(process and process.poll() is None),
        "authenticated": auth_file.exists() and auth_file.stat().st_size > 0,
        "auth_file": str(auth_file),
        "recent_logs": list(provider_auth_logs[provider])[-50:],
    }


@app.post("/api/providers/{provider}/auth/cancel")
async def provider_auth_cancel(provider: str) -> dict[str, Any]:
    if provider not in settings.provider_list:
        raise HTTPException(status_code=400, detail=f"provider 不支持: {provider}")
    with provider_auth_locks[provider]:
        process = provider_auth_processes.get(provider)
        if process and process.poll() is None:
            process.terminate()
            append_provider_auth_log(provider, "已请求停止认证流程")
    return {"ok": True}


async def proxy_to_codex_bridge(method: str, path: str, json_payload: dict[str, Any] | None = None) -> Response:
    url = f"{settings.code_mcp_bridge_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.request(method, url, json=json_payload)
            resp.raise_for_status()
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception as exc:
        return JSONResponse(status_code=502, content={"ok": False, "message": f"codex-mcp 不可用: {exc}"})


@app.post("/api/codex/oauth/start")
async def start_codex_oauth() -> Response:
    return await proxy_to_codex_bridge("POST", "/oauth/start")


@app.post("/api/codex/oauth/cancel")
async def cancel_codex_oauth() -> Response:
    return await proxy_to_codex_bridge("POST", "/oauth/cancel")


@app.get("/api/codex/oauth/status")
async def codex_oauth_status() -> Response:
    return await proxy_to_codex_bridge("GET", "/oauth/status")


@app.get("/api/codex/mcp/status")
async def codex_mcp_status() -> Response:
    return await proxy_to_codex_bridge("GET", "/mcp/status")


@app.get(settings.metrics_path)
async def metrics() -> Response:
    return render_metrics()


async def build_health_payload() -> dict[str, Any]:
    components: dict[str, Any] = {}
    healthy = True

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        components["database"] = {"status": "ok"}
    except Exception as exc:
        healthy = False
        components["database"] = {"status": "error", "detail": str(exc)}

    redis_client = None
    try:
        redis_client = redis_from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        await redis_client.ping()
        components["redis"] = {"status": "ok"}
    except Exception as exc:
        healthy = False
        components["redis"] = {"status": "error", "detail": str(exc)}
    finally:
        if redis_client is not None:
            await redis_client.aclose()

    try:
        components["minio"] = minio_client.healthcheck()
    except Exception as exc:
        healthy = False
        components["minio"] = {"status": "error", "detail": str(exc)}

    return {"ok": healthy, "app": settings.app_name, "components": components}


@app.get("/health")
async def health_root() -> JSONResponse:
    payload = await build_health_payload()
    return JSONResponse(status_code=200 if payload["ok"] else 503, content=payload)


@app.api_route("/preview/{site_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
@app.api_route("/preview/{site_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def preview_site(site_id: str, request: Request, path: str = "", db: AsyncSession = Depends(get_db)) -> Response:
    user = await get_legacy_user(db)
    site = await site_service.get_site_by_public_id(db, site_id, user)
    serialized = site_service.serialize_site(site)
    if serialized["status"] != "running":
        return HTMLResponse(
            content=f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>站点未运行</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f5f5f5}}
.card{{background:#fff;border-radius:12px;padding:40px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.1)}}
h2{{color:#303133;margin-bottom:12px}}p{{color:#909399}}</style></head>
<body><div class="card"><h2>站点未运行</h2><p>站点 <b>{site_id}</b> 当前处于停止状态，请先在管理面板中启动。</p></div></body></html>""",
            status_code=200,
        )
    return await proxy_to_sub_site(serialized, path, request)


@app.api_route("/sites/{site_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
@app.api_route("/sites/{site_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_site(site_id: str, request: Request, path: str = "", db: AsyncSession = Depends(get_db)) -> Response:
    user = await get_legacy_user(db)
    site = await site_service.get_site_by_public_id(db, site_id, user)
    serialized = site_service.serialize_site(site)
    if serialized["status"] != "running":
        return JSONResponse(status_code=409, content={"ok": False, "message": f"子网站未运行，请先启动：{site_id}"})
    return await proxy_to_sub_site(serialized, path, request)


@app.get("/api/health")
async def health() -> JSONResponse:
    payload = await build_health_payload()
    return JSONResponse(status_code=200 if payload["ok"] else 503, content=payload)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8080, reload=True)
