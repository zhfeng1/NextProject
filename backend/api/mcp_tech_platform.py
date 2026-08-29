from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import decode_token
from backend.models import Task, TaskStatus, User
from backend.services.execution_trace_service import redact_execution_text
from backend.services.task_service import task_service
from backend.services.tech_platform_deploy_service import tech_platform_deploy_service


router = APIRouter(prefix="/mcp/tech-platform")
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
LATEST_PROTOCOL_VERSION = "2025-06-18"


TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_tech_platform_modules",
        "description": "列出当前项目的技术中台部署模块及最近部署状态。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "scan_tech_platform_modules",
        "description": "重新扫描当前项目各仓库中的 Dockerfile。新模块不会自动填写命名空间。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "preview_tech_platform_yaml",
        "description": "渲染指定模块的 ConfigMap、Deployment、Service YAML；模块必须已配置命名空间。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module_id": {"type": "string", "description": "部署模块 ID"},
                "image": {"type": "string", "description": "可选的预览镜像地址"},
            },
            "required": ["module_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "validate_tech_platform_yaml",
        "description": "调用技术中台校验指定模块的全部 YAML；模块必须已有 appId。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module_id": {"type": "string", "description": "部署模块 ID"},
                "image": {"type": "string", "description": "可选的校验镜像地址"},
            },
            "required": ["module_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "deploy_tech_platform_module",
        "description": (
            "构建并推送镜像，然后将指定模块部署到技术中台。"
            "仅当用户明确要求部署且代码已准备好时调用；返回异步任务 ID。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"module_id": {"type": "string", "description": "部署模块 ID"}},
            "required": ["module_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "get_tech_platform_deploy_status",
        "description": "查询技术中台部署任务状态、结果及增量日志。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "deploy 工具返回的任务 ID"},
                "after_log_id": {"type": "integer", "minimum": 0, "default": 0},
                "log_limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
            },
            "required": ["task_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


def _rpc_result(request_id: Any, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _rpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )


async def _authenticate(
    authorization: str,
    db: AsyncSession,
) -> tuple[User, Task, str]:
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="MCP token is required")
    try:
        payload = decode_token(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid MCP token") from exc
    if payload.get("type") != "programming_mcp":
        raise HTTPException(status_code=401, detail="Invalid MCP token type")
    user_id = str(payload.get("sub") or "")
    task_id = str(payload.get("task_id") or "")
    project_id = str(payload.get("project_id") or "")
    user = await db.get(User, user_id)
    task = await db.get(Task, task_id)
    if user is None or not user.is_active or task is None:
        raise HTTPException(status_code=401, detail="MCP task context is unavailable")
    if (
        task.status != TaskStatus.RUNNING.value
        or str(task.project_id or "") != project_id
        or task.task_type != "develop_code"
    ):
        raise HTTPException(status_code=401, detail="MCP task context is no longer active")
    return user, task, project_id


def _compact_module(module: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "site_id",
        "site_name",
        "dockerfile_path",
        "build_context",
        "app_name",
        "namespace",
        "harbor_project",
        "repository_name",
        "app_type",
        "container_port",
        "service_port",
        "platform_app_id",
        "is_available",
        "last_task_id",
        "last_image",
        "last_commit_sha",
        "status",
        "last_error",
        "last_deployed_at",
    )
    return {key: module.get(key) for key in keys}


def _required_string(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} 不能为空")
    return value


async def _call_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    user: User,
    context_task: Task,
    project_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    if name == "list_tech_platform_modules":
        modules = await tech_platform_deploy_service.list_modules(db, project_id, user)
        return {"project_id": project_id, "modules": [_compact_module(item) for item in modules]}
    if name == "scan_tech_platform_modules":
        await task_service.append_log(db, context_task, "MCP 调用：扫描技术中台部署模块", source="mcp")
        modules = await tech_platform_deploy_service.scan_modules(db, project_id, user)
        return {"project_id": project_id, "modules": [_compact_module(item) for item in modules]}
    if name == "preview_tech_platform_yaml":
        return await tech_platform_deploy_service.preview_module(
            db,
            project_id,
            _required_string(arguments, "module_id"),
            user,
            str(arguments.get("image") or ""),
        )
    if name == "validate_tech_platform_yaml":
        return await tech_platform_deploy_service.validate_module(
            db,
            project_id,
            _required_string(arguments, "module_id"),
            user,
            str(arguments.get("image") or ""),
        )
    if name == "deploy_tech_platform_module":
        module_id = _required_string(arguments, "module_id")
        await task_service.append_log(
            db, context_task, f"MCP 调用：提交技术中台部署（module_id={module_id}）", source="mcp"
        )
        deploy_task = await tech_platform_deploy_service.create_deploy_task(
            db, project_id, module_id, user
        )
        return {
            "ok": True,
            "task_id": str(deploy_task.id),
            "task": task_service.serialize_task(deploy_task),
        }
    if name == "get_tech_platform_deploy_status":
        deploy_task = await task_service.get_task(
            db, _required_string(arguments, "task_id"), user
        )
        if str(deploy_task.project_id or "") != project_id:
            raise HTTPException(status_code=404, detail="部署任务不存在")
        after_log_id = max(0, int(arguments.get("after_log_id") or 0))
        log_limit = min(200, max(1, int(arguments.get("log_limit") or 100)))
        logs = await task_service.get_task_logs(
            db, str(deploy_task.id), user, after_id=after_log_id, limit=log_limit
        )
        return {
            "task": await task_service.serialize_task_detail(db, deploy_task),
            "logs": logs,
            "next_after_log_id": logs[-1]["id"] if logs else after_log_id,
        }
    raise ValueError(f"未知工具: {name}")


@router.post("")
async def handle_tech_platform_mcp(
    payload: Any = Body(...),
    authorization: str = Header(default="", alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    user, context_task, project_id = await _authenticate(authorization, db)
    if not isinstance(payload, dict):
        return _rpc_error(None, -32600, "Invalid Request")
    request_id = payload.get("id")
    method = str(payload.get("method") or "")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    if method == "initialize":
        requested = str(params.get("protocolVersion") or "")
        protocol_version = (
            requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
        )
        return _rpc_result(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "NextProject Tech Platform", "version": "1.0.0"},
                "instructions": (
                    "这些工具仅操作当前编程任务所属项目。部署前先列出模块并确认 namespace 已由用户配置。"
                ),
            },
        )
    if method.startswith("notifications/"):
        return Response(status_code=202)
    if method == "ping":
        return _rpc_result(request_id, {})
    if method == "tools/list":
        return _rpc_result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            result = await _call_tool(
                name=name,
                arguments=arguments,
                user=user,
                context_task=context_task,
                project_id=project_id,
                db=db,
            )
            return _rpc_result(
                request_id,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                    ],
                    "structuredContent": result,
                    "isError": False,
                },
            )
        except (HTTPException, ValueError) as exc:
            message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        except Exception as exc:  # pragma: no cover - final safety boundary
            message = redact_execution_text(str(exc)) or "工具执行失败"
        return _rpc_result(
            request_id,
            {
                "content": [{"type": "text", "text": str(message)}],
                "isError": True,
            },
        )
    return _rpc_error(request_id, -32601, f"Method not found: {method}")


@router.delete("")
async def close_tech_platform_mcp_session() -> Response:
    return Response(status_code=204)
