from __future__ import annotations

import random
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin

import httpx


class TechPlatformError(RuntimeError):
    pass


def _random_value() -> int:
    return random.SystemRandom().randint(1, 99999)


def _first_key_value(value: Any, key_name: str) -> Any | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() == key_name.lower():
                return item
        for item in value.values():
            found = _first_key_value(item, key_name)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first_key_value(item, key_name)
            if found is not None:
                return found
    return None


class TechPlatformClient:
    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        system_id: str,
        verify_ssl: bool = False,
        timeout_seconds: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.username = username.strip()
        self.password = password.strip()
        self.system_id = system_id.strip()
        self.token = ""
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=10),
            verify=verify_ssl,
            follow_redirects=False,
        )

    async def __aenter__(self) -> "TechPlatformClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.client.aclose()

    def _headers(self) -> dict[str, str]:
        origin = self.base_url.rstrip("/")
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": origin,
            "Referer": f"{origin}/apollo-web/",
            "System-Id": self.system_id,
            "User-Agent": "NextProject-Tech-Platform-Deploy/1.0",
        }
        if self.token:
            headers["X-User-Token"] = self.token
        return headers

    @staticmethod
    def _assert_business_success(data: Any, operation: str) -> None:
        if not isinstance(data, dict):
            return
        code = data.get("code")
        if code is not None and str(code) not in {"00000", "0", "200"}:
            message = data.get("message") or data.get("msg") or f"code={code}"
            raise TechPlatformError(f"{operation}失败: {message}")
        if data.get("success") is False:
            message = data.get("message") or data.get("msg") or "平台返回失败"
            raise TechPlatformError(f"{operation}失败: {message}")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        operation: str,
        sensitive: bool = False,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        try:
            response = await self.client.request(
                method,
                urljoin(self.base_url, path.lstrip("/")),
                json=payload,
                params=params,
                headers=self._headers(),
            )
            if (
                response.status_code in {401, 403}
                and retry_auth
                and operation != "技术中台登录"
                and self.username
                and self.password
            ):
                self.token = ""
                await self.login()
                return await self._request_json(
                    method,
                    path,
                    payload=payload,
                    params=params,
                    operation=operation,
                    sensitive=sensitive,
                    retry_auth=False,
                )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = ""
            if not sensitive:
                detail = f": {exc.response.text[:400]}"
            raise TechPlatformError(
                f"{operation}请求失败 ({exc.response.status_code}){detail}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise TechPlatformError(f"{operation}请求失败: {exc}") from exc
        self._assert_business_success(data, operation)
        if not isinstance(data, dict):
            raise TechPlatformError(f"{operation}返回了无效 JSON")
        return data

    async def login(self) -> str:
        if not self.username or not self.password or not self.system_id:
            raise TechPlatformError("技术中台登录环境变量未配置完整")
        data = await self._request_json(
            "POST",
            "/apollo/user/login",
            payload={
                "tel": self.username,
                "password": self.password,
                "rememberMe": True,
                "random": _random_value(),
            },
            operation="技术中台登录",
            sensitive=True,
            retry_auth=False,
        )
        token = _first_key_value(data, "token")
        self.token = str(token or "").strip()
        if not self.token:
            raise TechPlatformError("技术中台登录成功响应中没有 token")
        return self.token

    async def save_application(
        self,
        *,
        app_id: str,
        app_name: str,
        harbor_project: str,
        repository_name: str,
        image_tag: str,
        app_type: str,
    ) -> tuple[str, dict[str, Any]]:
        payload = {
            "resources": [],
            "appName": app_name,
            "mark": app_name,
            "harborProjectName": harbor_project,
            "repositoryName": repository_name,
            "imageTag": image_tag,
            "appType": app_type,
            "random": _random_value(),
        }
        path = (
            f"/devops/cicd/v1.0/job/{app_id}/saveAll"
            if app_id
            else "/devops/cicd/v1.0/job/saveAll"
        )
        data = await self._request_json(
            "POST",
            path,
            payload=payload,
            operation="更新中台应用" if app_id else "新建中台应用",
        )
        if app_id:
            return app_id, data
        result = data.get("result")
        result_data = result.get("data") if isinstance(result, dict) else None
        first = (
            result_data[0] if isinstance(result_data, list) and result_data else None
        )
        if isinstance(first, dict):
            first = first.get("appId") or first.get("id")
        created_id = str(first or "").strip()
        if not created_id:
            raise TechPlatformError("新建中台应用成功响应中没有 result.data[0]")
        return created_id, data

    async def get_yaml_resource_types(self) -> dict[str, int]:
        data = await self._request_json(
            "GET",
            "/devops/cicd/v1.0/job/yaml/template",
            operation="获取中台 YAML 类型模板",
        )
        mapping: dict[str, int] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                kind = (
                    value.get("kind")
                    or value.get("k8sKind")
                    or value.get("resourceKind")
                    or value.get("name")
                )
                resource_type = value.get("resourceType")
                if resource_type is None:
                    resource_type = value.get("resource_type")
                if resource_type is None and kind:
                    resource_type = value.get("value") or value.get("type")
                if kind and resource_type is not None:
                    try:
                        mapping[str(kind).strip().lower()] = int(resource_type)
                    except (TypeError, ValueError):
                        pass
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(data)
        return mapping

    async def check_yaml(
        self,
        *,
        app_id: str,
        kind: str,
        resource_type: int,
        yaml_text: str,
    ) -> dict[str, Any]:
        data = await self._request_json(
            "POST",
            "/devops/cicd/k8s/yaml/checkYaml",
            payload={
                "appId": int(app_id) if app_id.isdigit() else app_id,
                "resource": {
                    "resourceType": resource_type,
                    "yaml": yaml_text,
                    "kind": kind,
                },
                "random": _random_value(),
            },
            operation=f"校验 {kind}",
        )
        error_type = _first_key_value(data, "errorType")
        if error_type is not None and str(error_type) not in {"0", "", "None"}:
            message = (
                _first_key_value(data, "message")
                or _first_key_value(data, "msg")
                or "YAML 校验未通过"
            )
            raise TechPlatformError(
                f"{kind} 校验失败 (errorType={error_type}): {message}"
            )
        return data

    async def deploy_yaml(
        self,
        *,
        app_id: str,
        kind: str,
        resource_type: int,
        yaml_text: str,
    ) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            "/devops/cicd/v1.0/job/deployItem",
            payload={
                "appId": int(app_id) if app_id.isdigit() else app_id,
                "resource": {
                    "resourceType": resource_type,
                    "yaml": yaml_text,
                    "kind": kind,
                },
                "random": _random_value(),
            },
            operation=f"部署 {kind}",
        )


def required_resource_types(
    mapping: dict[str, int], kinds: Iterable[str]
) -> dict[str, int]:
    result: dict[str, int] = {}
    missing: list[str] = []
    for kind in kinds:
        value = mapping.get(kind.lower())
        if value is None:
            missing.append(kind)
        else:
            result[kind] = value
    if missing:
        raise TechPlatformError(f"中台 YAML 类型模板缺少: {', '.join(missing)}")
    return result
