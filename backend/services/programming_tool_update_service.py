from __future__ import annotations

import asyncio
import io
import json
import re
import tarfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from backend.services.programming_tool_service import programming_tool_service


DOCKER_SOCKET = "/var/run/docker.sock"
LATEST_VERSION_CACHE_SECONDS = 300
ACTIVE_UPDATE_STATUSES = frozenset({"queued", "building", "restarting"})


@dataclass(frozen=True, slots=True)
class ProgrammingToolUpdateSpec:
    id: str
    label: str
    package_name: str
    service_name: str
    container_name: str
    image_name: str


@dataclass(slots=True)
class ProgrammingToolUpdateState:
    status: str = "idle"
    message: str = ""
    target_version: str = ""
    started_at: str | None = None
    finished_at: str | None = None


TOOL_UPDATE_SPECS = (
    ProgrammingToolUpdateSpec(
        id="codex",
        label="Codex",
        package_name="@openai/codex",
        service_name="codex-adapter",
        container_name="nextproject-codex-adapter",
        image_name="nextproject-codex-adapter:latest",
    ),
    ProgrammingToolUpdateSpec(
        id="claude_code",
        label="Claude Code",
        package_name="@anthropic-ai/claude-code",
        service_name="claude-code-adapter",
        container_name="nextproject-claude-code-adapter",
        image_name="nextproject-claude-code-adapter:latest",
    ),
    ProgrammingToolUpdateSpec(
        id="codebuddy",
        label="CodeBuddy",
        package_name="@tencent-ai/codebuddy-code",
        service_name="codebuddy-adapter",
        container_name="nextproject-codebuddy-adapter",
        image_name="nextproject-codebuddy-adapter:latest",
    ),
    ProgrammingToolUpdateSpec(
        id="opencode",
        label="OpenCode",
        package_name="opencode-ai",
        service_name="opencode-adapter",
        container_name="nextproject-opencode-adapter",
        image_name="nextproject-opencode-adapter:latest",
    ),
    ProgrammingToolUpdateSpec(
        id="kimi_code",
        label="Kimi Code",
        package_name="@moonshot-ai/kimi-code",
        service_name="kimi-code-adapter",
        container_name="nextproject-kimi-code-adapter",
        image_name="nextproject-kimi-code-adapter:latest",
    ),
)
TOOL_UPDATE_SPECS_BY_ID = {spec.id: spec for spec in TOOL_UPDATE_SPECS}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_version(raw: str) -> str:
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)", raw or "")
    return match.group(1) if match else ""


def _version_key(version: str) -> tuple[int, int, int, int, str]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([^+]+))?", version or "")
    if not match:
        return (0, 0, 0, 0, version or "")
    prerelease = match.group(4) or ""
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        1 if not prerelease else 0,
        prerelease,
    )


class ProgrammingToolUpdateService:
    def __init__(self) -> None:
        self._states = {spec.id: ProgrammingToolUpdateState() for spec in TOOL_UPDATE_SPECS}
        self._latest_cache: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @staticmethod
    def _spec(tool_id: str) -> ProgrammingToolUpdateSpec:
        spec = TOOL_UPDATE_SPECS_BY_ID.get(tool_id)
        if spec is None:
            raise HTTPException(status_code=404, detail="不支持的编程工具")
        return spec

    async def _latest_version(self, spec: ProgrammingToolUpdateSpec, *, refresh: bool = False) -> str:
        cached = self._latest_cache.get(spec.id)
        if not refresh and cached and time.monotonic() - cached[0] < LATEST_VERSION_CACHE_SECONDS:
            return cached[1]
        package_path = quote(spec.package_name, safe="")
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(f"https://registry.npmjs.org/{package_path}/latest")
                response.raise_for_status()
                version = str(response.json().get("version") or "").strip()
        except (httpx.HTTPError, ValueError) as exc:
            if cached:
                return cached[1]
            raise RuntimeError(f"无法查询 npm 最新版本：{exc}") from exc
        if not version:
            raise RuntimeError("npm 返回的最新版本为空")
        self._latest_cache[spec.id] = (time.monotonic(), version)
        return version

    async def list_versions(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        health_results = await asyncio.gather(
            *(programming_tool_service.adapter_health(spec.id) for spec in TOOL_UPDATE_SPECS)
        )
        latest_results = await asyncio.gather(
            *(self._latest_version(spec, refresh=refresh) for spec in TOOL_UPDATE_SPECS),
            return_exceptions=True,
        )
        tools: list[dict[str, Any]] = []
        for spec, health_result, latest_result in zip(
            TOOL_UPDATE_SPECS,
            health_results,
            latest_results,
            strict=True,
        ):
            healthy, health = health_result
            current_raw = str(health.get("version") or "")
            current_version = _extract_version(current_raw)
            latest_error = ""
            if isinstance(latest_result, BaseException):
                latest_version = ""
                latest_error = str(latest_result)
            else:
                latest_version = latest_result
            has_update = bool(
                current_version
                and latest_version
                and _version_key(latest_version) > _version_key(current_version)
            )
            state = asdict(self._states[spec.id])
            tools.append(
                {
                    "id": spec.id,
                    "label": spec.label,
                    "package_name": spec.package_name,
                    "service_name": spec.service_name,
                    "healthy": healthy,
                    "current_version": current_version,
                    "current_version_raw": current_raw,
                    "latest_version": latest_version,
                    "latest_error": latest_error,
                    "has_update": has_update,
                    "updating": state["status"] in ACTIVE_UPDATE_STATUSES,
                    **state,
                }
            )
        return tools

    async def start_update(self, tool_id: str) -> dict[str, Any]:
        spec = self._spec(tool_id)
        async with self._lock:
            state = self._states[tool_id]
            if state.status in ACTIVE_UPDATE_STATUSES:
                raise HTTPException(status_code=409, detail=f"{spec.label} 正在更新")
            try:
                latest_version = await self._latest_version(spec, refresh=True)
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            state.status = "queued"
            state.message = "等待构建最新镜像"
            state.target_version = latest_version
            state.started_at = _utc_now()
            state.finished_at = None
            task = asyncio.create_task(self._run_update(spec, latest_version))
            self._tasks[tool_id] = task
            task.add_done_callback(lambda _: self._tasks.pop(tool_id, None))
            return {"ok": True, "tool_id": tool_id, "target_version": latest_version, "status": state.status}

    async def _run_update(self, spec: ProgrammingToolUpdateSpec, version: str) -> None:
        state = self._states[spec.id]
        try:
            state.status = "building"
            state.message = f"正在构建 {spec.label} {version} 镜像"
            image_id = await self._build_image(spec, version, state)
            state.status = "restarting"
            state.message = "镜像构建完成，正在替换并启动适配器"
            await self._replace_container(spec, image_id, state)
            state.status = "success"
            state.message = f"已更新到 {version}"
        except Exception as exc:
            state.status = "failed"
            state.message = str(exc)[:500]
        finally:
            state.finished_at = _utc_now()

    @staticmethod
    def _build_context() -> bytes:
        root = Path(__file__).resolve().parents[2] / "programming_tool_adapter"
        if not (root / "Dockerfile").is_file():
            raise RuntimeError("主服务镜像中缺少编程工具构建文件")
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(root)
                if "__pycache__" in relative.parts or "tests" in relative.parts or path.suffix == ".pyc":
                    continue
                archive.add(path, arcname=str(Path("programming_tool_adapter") / relative), recursive=False)
        return output.getvalue()

    @staticmethod
    async def _docker_client() -> tuple[httpx.AsyncClient, str]:
        if not Path(DOCKER_SOCKET).exists():
            raise RuntimeError("Docker Socket 未挂载到 main-service")
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET)
        client = httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=httpx.Timeout(30))
        try:
            response = await client.get("/version")
            response.raise_for_status()
            api_version = str(response.json().get("ApiVersion") or "").strip()
        except Exception:
            await client.aclose()
            raise
        if not api_version:
            await client.aclose()
            raise RuntimeError("无法获取 Docker API 版本")
        return client, f"/v{api_version}"

    @staticmethod
    def _docker_error(response: httpx.Response) -> str:
        try:
            return str(response.json().get("message") or response.text)
        except ValueError:
            return response.text

    async def _build_image(
        self,
        spec: ProgrammingToolUpdateSpec,
        version: str,
        state: ProgrammingToolUpdateState,
    ) -> str:
        client, api = await self._docker_client()
        try:
            params = {
                "dockerfile": "programming_tool_adapter/Dockerfile",
                "t": spec.image_name,
                "rm": "1",
                "forcerm": "1",
                "version": "2",
                "buildargs": json.dumps({"TOOL_ID": spec.id, "TOOL_VERSION": version}),
            }
            async with client.stream(
                "POST",
                f"{api}/build",
                params=params,
                content=self._build_context(),
                headers={"Content-Type": "application/x-tar"},
                timeout=None,
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise RuntimeError(f"Docker 镜像构建失败：{body.decode(errors='replace')[:500]}")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("error") or event.get("errorDetail"):
                        detail = event.get("errorDetail", {}).get("message") or event.get("error")
                        raise RuntimeError(f"Docker 镜像构建失败：{detail}")
                    message = str(event.get("stream") or event.get("status") or "").strip()
                    if message:
                        state.message = message.splitlines()[-1][:240]
            encoded_image = quote(spec.image_name, safe="")
            response = await client.get(f"{api}/images/{encoded_image}/json")
            if response.status_code >= 400:
                raise RuntimeError(f"无法读取新镜像：{self._docker_error(response)}")
            image_id = str(response.json().get("Id") or "")
            if not image_id:
                raise RuntimeError("新镜像没有有效的镜像 ID")
            return image_id
        finally:
            await client.aclose()

    async def _replace_container(
        self,
        spec: ProgrammingToolUpdateSpec,
        image_id: str,
        state: ProgrammingToolUpdateState,
    ) -> None:
        client, api = await self._docker_client()
        original_name = spec.container_name
        backup_name = f"{original_name}-backup-{uuid.uuid4().hex[:8]}"
        renamed = False
        try:
            inspect_response = await client.get(f"{api}/containers/{quote(original_name, safe='')}/json")
            if inspect_response.status_code >= 400:
                raise RuntimeError(f"无法读取当前容器：{self._docker_error(inspect_response)}")
            current = inspect_response.json()
            await self._expect(client.post(f"{api}/containers/{quote(original_name, safe='')}/stop", params={"t": 30}), {204, 304})
            await self._expect(
                client.post(
                    f"{api}/containers/{quote(original_name, safe='')}/rename",
                    params={"name": backup_name},
                ),
                {204},
            )
            renamed = True
            payload = self._replacement_payload(current, spec, image_id)
            create_response = await client.post(
                f"{api}/containers/create",
                params={"name": original_name},
                json=payload,
            )
            if create_response.status_code != 201:
                raise RuntimeError(f"创建新容器失败：{self._docker_error(create_response)}")
            await self._expect(
                client.post(f"{api}/containers/{quote(original_name, safe='')}/start"),
                {204, 304},
            )
            await self._wait_until_healthy(client, api, original_name, state)
            await self._expect(
                client.delete(f"{api}/containers/{quote(backup_name, safe='')}", params={"force": "1"}),
                {204},
            )
        except Exception:
            if renamed:
                await self._rollback_container(client, api, original_name, backup_name)
            raise
        finally:
            await client.aclose()

    async def _expect(self, awaitable: Any, expected: set[int]) -> httpx.Response:
        response = await awaitable
        if response.status_code not in expected:
            raise RuntimeError(self._docker_error(response))
        return response

    @staticmethod
    def _replacement_payload(
        current: dict[str, Any],
        spec: ProgrammingToolUpdateSpec,
        image_id: str,
    ) -> dict[str, Any]:
        config = current.get("Config") or {}
        host = current.get("HostConfig") or {}
        labels = dict(config.get("Labels") or {})
        labels["com.docker.compose.image"] = image_id
        labels["com.docker.compose.replace"] = spec.container_name
        replacement: dict[str, Any] = {
            "Hostname": config.get("Hostname") or "",
            "Domainname": config.get("Domainname") or "",
            "User": config.get("User") or "",
            "AttachStdin": False,
            "AttachStdout": True,
            "AttachStderr": True,
            "ExposedPorts": config.get("ExposedPorts") or {},
            "Tty": bool(config.get("Tty")),
            "OpenStdin": bool(config.get("OpenStdin")),
            "StdinOnce": bool(config.get("StdinOnce")),
            "Env": config.get("Env") or [],
            "Cmd": config.get("Cmd"),
            "Healthcheck": config.get("Healthcheck"),
            "Image": spec.image_name,
            "Volumes": config.get("Volumes") or {},
            "WorkingDir": config.get("WorkingDir") or "",
            "Entrypoint": config.get("Entrypoint"),
            "Labels": labels,
            "StopSignal": config.get("StopSignal") or "SIGTERM",
            "HostConfig": {
                "Binds": host.get("Binds") or [],
                "LogConfig": host.get("LogConfig") or {},
                "NetworkMode": host.get("NetworkMode") or "default",
                "RestartPolicy": host.get("RestartPolicy") or {"Name": "unless-stopped"},
                "AutoRemove": bool(host.get("AutoRemove")),
                "ReadonlyRootfs": bool(host.get("ReadonlyRootfs")),
                "Tmpfs": host.get("Tmpfs") or {},
                "ShmSize": int(host.get("ShmSize") or 67108864),
            },
        }
        endpoints: dict[str, Any] = {}
        for network_name, network in (current.get("NetworkSettings", {}).get("Networks") or {}).items():
            aliases = [
                alias
                for alias in (network.get("Aliases") or [])
                if alias and not re.fullmatch(r"[0-9a-f]{12}", alias)
            ]
            endpoints[network_name] = {"Aliases": aliases}
        if endpoints:
            replacement["NetworkingConfig"] = {"EndpointsConfig": endpoints}
        return replacement

    async def _wait_until_healthy(
        self,
        client: httpx.AsyncClient,
        api: str,
        container_name: str,
        state: ProgrammingToolUpdateState,
    ) -> None:
        deadline = time.monotonic() + 90
        encoded_name = quote(container_name, safe="")
        while time.monotonic() < deadline:
            response = await client.get(f"{api}/containers/{encoded_name}/json")
            if response.status_code >= 400:
                raise RuntimeError(f"读取新容器状态失败：{self._docker_error(response)}")
            container_state = response.json().get("State") or {}
            status = str(container_state.get("Status") or "")
            health = str((container_state.get("Health") or {}).get("Status") or "")
            if status in {"dead", "exited"}:
                error = str(container_state.get("Error") or "容器已退出")
                raise RuntimeError(f"新容器启动失败：{error}")
            if status == "running" and (not health or health == "healthy"):
                return
            state.message = f"等待适配器健康检查（{health or status or 'starting'}）"
            await asyncio.sleep(2)
        raise RuntimeError("新容器健康检查超时，已回滚旧版本")

    async def _rollback_container(
        self,
        client: httpx.AsyncClient,
        api: str,
        original_name: str,
        backup_name: str,
    ) -> None:
        original = quote(original_name, safe="")
        backup = quote(backup_name, safe="")
        response = await client.get(f"{api}/containers/{original}/json")
        if response.status_code == 200:
            await client.delete(f"{api}/containers/{original}", params={"force": "1"})
        response = await client.post(f"{api}/containers/{backup}/rename", params={"name": original_name})
        if response.status_code == 204:
            await client.post(f"{api}/containers/{original}/start")


programming_tool_update_service = ProgrammingToolUpdateService()
