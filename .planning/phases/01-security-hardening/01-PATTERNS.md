# Phase 1: 安全加固与基础设施加固 - Patterns

**Generated:** 2026-04-23
**Status:** Complete

---

## 1. 文件清单与角色分类

### 1.1 后端 — 配置层 (Config)

| 文件 | 变更类型 | 角色 | 数据流 |
|------|---------|------|--------|
| `backend/core/config.py` | 修改 | 配置入口 | `.env` → Settings 单例 → 全局 |
| `.env.example` | 修改 | 配置模板 | 开发者参考 |
| `docker-compose.yml` | 修改 | 部署配置 | 环境变量注入容器 |

### 1.2 后端 — 安全工具层 (Security Utility)

| 文件 | 变更类型 | 角色 | 数据流 |
|------|---------|------|--------|
| `backend/core/encryption.py` | **新建** | 加密/解密/脱敏工具 | 被 providers API + task_service 调用 |

### 1.3 后端 — API 层 (API Endpoint)

| 文件 | 变更类型 | 角色 | 数据流 |
|------|---------|------|--------|
| `backend/api/v2/providers.py` | 修改 | Provider CRUD + 模型验证 | HTTP ↔ DB (加密写入 / 脱敏返回) |

### 1.4 后端 — 服务层 (Service)

| 文件 | 变更类型 | 角色 | 数据流 |
|------|---------|------|--------|
| `backend/services/task_service.py` | 修改 | 任务执行核心 | DB(密文) → 解密 → 临时文件 → 子进程 |

### 1.5 后端 — 任务层 (Celery Task)

| 文件 | 变更类型 | 角色 | 数据流 |
|------|---------|------|--------|
| `backend/tasks/develop_code.py` | 修改 | AI 开发任务入口 | Redis 锁 → task_service → 锁释放 |

### 1.6 后端 — 数据迁移 (Data Migration)

| 文件 | 变更类型 | 角色 | 数据流 |
|------|---------|------|--------|
| `backend/alembic/versions/xxxx_encrypt_api_keys.py` | **新建** | 明文→密文数据迁移 | DB 批量读取 → 加密 → 回写 |

### 1.7 前端

| 文件 | 变更类型 | 角色 | 数据流 |
|------|---------|------|--------|
| `frontend/src/api/providers.ts` | 修改 | API 客户端 | 新增 `verifyModel()` 方法 |
| `frontend/src/views/Settings/Account.vue` | 修改 | 设置页面 | 脱敏值展示 + 验证按钮 |

---

## 2. 各文件的最近类比与代码摘录

### 2.1 `backend/core/config.py` — 添加 `fernet_key` 配置项

**最近类比：** 同文件中 `secret_key` 字段（L35）— 同为必需安全密钥，有校验器。

**现有模式摘录：**
```python
# backend/core/config.py:35-36
secret_key: str = Field(alias="SECRET_KEY")
jwt_algorithm: str = "HS256"
```

**校验器模式摘录：**
```python
# backend/core/config.py:92-103
@field_validator("secret_key")
@classmethod
def validate_secret_key(cls, value: str) -> str:
    value = value.strip()
    if not value or value == "change-me-in-production":
        raise ValueError(
            "SECRET_KEY must be set to a secure non-default value. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    if len(value) < 32:
        raise ValueError("SECRET_KEY must be at least 32 characters long")
    return value
```

**新增模式：**
- 添加 `fernet_key: str = Field(alias="FERNET_KEY")`
- 添加 `@field_validator("fernet_key")` 校验合法 Fernet key（base64 + 44 字符）
- 位置：紧接 `secret_key` 之后

---

### 2.2 `backend/core/encryption.py` — 新建加密工具模块

**最近类比：** `backend/core/security.py` — 同为 `core/` 下的安全工具模块。

**现有模式摘录（security.py 的模块结构）：**
```python
# backend/core/security.py:1-18
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models import User
from backend.core.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
SECRET_KEY = settings.secret_key
```

```python
# backend/core/security.py:85-98
__all__ = [
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "ALGORITHM",
    ...
]
```

**新模块应遵循的模式：**
- 模块级 `settings = get_settings()` 获取配置
- 模块级初始化加密实例（如 `_fernet = Fernet(settings.fernet_key.encode())`）
- 导出 `encrypt_api_key()`、`decrypt_api_key()`、`mask_api_key()` 三个函数
- 使用 `__all__` 控制导出

---

### 2.3 `backend/api/v2/providers.py` — 脱敏、加密、跳过脱敏值更新、验证端点

**最近类比（序列化）：** 同文件 `_serialize()` 函数（L17-29）。

**现有模式摘录：**
```python
# backend/api/v2/providers.py:17-29
def _serialize(p: UserLLMProvider) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "name": p.name,
        "base_url": p.base_url,
        "api_key": p.api_key,          # ← 改为 mask_api_key(decrypt_api_key(p.api_key))
        "models": p.models or [],
        "format": p.format,
        "is_default": bool(p.is_default),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
```

**最近类比（创建时字段处理）：** 同文件 create_provider（L51-56）。

```python
# backend/api/v2/providers.py:51-58
p = UserLLMProvider(
    id=str(uuid.uuid4()),
    user_id=user_id,
    name=(payload.get("name") or "").strip() or "New Provider",
    base_url=(payload.get("base_url") or "").strip(),
    api_key=(payload.get("api_key") or "").strip(),   # ← 改为 encrypt_api_key(...)
    models=payload.get("models") or [],
    format=payload.get("format") or "responses",
    is_default=bool(payload.get("is_default", False)),
)
```

**最近类比（更新时字段处理）：** 同文件 update_provider（L78-81）。

```python
# backend/api/v2/providers.py:78-81
allowed = {"name", "base_url", "api_key", "models", "format", "is_default"}
for key, value in payload.items():
    if key in allowed:
        setattr(p, key, value)
# ← 需增加：if key == "api_key" 时检查 "****"，跳过脱敏值；否则 encrypt
```

**最近类比（外部 API 调用）：** 同文件 `fetch-models` 端点（L102-123）。

```python
# backend/api/v2/providers.py:111-123
try:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data") or data.get("models") or []
        model_ids = sorted([m["id"] if isinstance(m, dict) else str(m) for m in models])
        return {"ok": True, "models": model_ids}
except Exception as exc:
    return {"ok": False, "models": [], "error": str(exc)}
```

**新 `verify-model` 端点应遵循的模式：**
- 同样使用 `httpx.AsyncClient(timeout=10)`
- 返回格式 `{"ok": True/False, ...}` 与 `fetch-models` 一致
- 使用 `Depends(get_current_user)` 保护
- 从 `provider_id` 读取 DB 中的加密 Key，解密后用于验证（前端不传明文）
- 根据 `format` 字段选择不同的 API 路径和请求体

---

### 2.4 `backend/services/task_service.py` — 解密 Key + 临时文件 + Runtime 清理

**最近类比（环境变量设置）：** 同文件 `_run_develop_task_for_provider`（L592-596）。

```python
# backend/services/task_service.py:592-598
if llm_provider and llm_provider.api_key:
    model_name = (llm_provider.models or [""])[0] if llm_provider.models else ""
    if provider == "codex":
        extra_env["CODEX_TASK_API_KEY"] = llm_provider.api_key  # ← 改为写临时文件
        extra_env["CODEX_TASK_HOME"] = f"/tmp/nextproject-codex/{task.id}"
        if llm_provider.base_url:
            extra_env["CODEX_TASK_OPENAI_BASE_URL"] = llm_provider.base_url
```

```python
# backend/services/task_service.py:619-621
elif provider == "claude_code":
    extra_env["ANTHROPIC_API_KEY"] = llm_provider.api_key  # ← 改为写临时文件
    if llm_provider.base_url:
        extra_env["ANTHROPIC_BASE_URL"] = llm_provider.base_url
```

**最近类比（runtime 文件写入）：** 同文件 `_write_runtime_file`（L89-93）。

```python
# backend/services/task_service.py:89-93
@staticmethod
def _write_runtime_file(root: Path, filename: str, data: dict[str, Any] | list[Any]) -> str:
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
```

**最近类比（runtime 目录使用）：** 同文件 L556。

```python
# backend/services/task_service.py:556
runtime_context_root = Path("/tmp/nextproject-task-runtime") / str(task.id)
```

**新增模式：**
- API Key 临时文件写入：复用 `runtime_context_root`，写入 `api_key` 文件，权限 `0o600`
- `_cleanup_task_runtime(task_id)` 方法：在 `update_status()` 中当 `status` 为终态时调用
- Shell 脚本改造：`printf %s "${CODEX_TASK_API_KEY}" |` → `printf %s "$(cat "$CODEX_TASK_API_KEY_FILE")" |`

**最近类比（状态更新钩子）：** 同文件 `update_status`（L216-242）。

```python
# backend/services/task_service.py:229-232
if status_value == TaskStatus.RUNNING.value:
    task.started_at = now
if status_value in {TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELED.value}:
    task.finished_at = now
# ← 在此处添加 runtime 清理调用
```

---

### 2.5 `backend/tasks/develop_code.py` — Redis 分布式锁集成

**最近类比：** 同文件现有 Celery task 定义（L10-17）。

```python
# backend/tasks/develop_code.py:10-17
@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def develop_code_task(self, task_id: str) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        async with task_db_session() as db:
            task = await task_service.run_develop_task(db, task_id)
            return task_service.serialize_task(task)

    return asyncio.run(_run())
```

**新增模式：**
- `max_retries` 改为 60，`default_retry_delay` 改为 30（锁等待）
- 在 `_run()` 前获取 `site_id`，尝试 `acquire_site_lock()`
- 获取失败则 `raise self.retry(countdown=30)`
- `finally` 中 `release_site_lock()`
- Redis 客户端：`redis.Redis.from_url(settings.redis_url)`

**最近类比（Redis 连接）：** `backend/core/celery_app.py`（L6-8）。

```python
# backend/core/celery_app.py:6-8
settings = get_settings()
celery_app = Celery(
    "nextproject",
    broker=settings.celery_broker_url,
```

---

### 2.6 `backend/alembic/versions/xxxx_encrypt_api_keys.py` — 数据迁移

**最近类比：** `backend/alembic/versions/20260323_0004_add_user_llm_providers.py` — 同表的 schema 迁移。

```python
# backend/alembic/versions/20260323_0004_add_user_llm_providers.py:1-10
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260323_0004"
down_revision = "20260323_0003"
branch_labels = None
depends_on = None
```

**Alembic data migration 模式（需使用）：**
```python
# 标准 data migration 模式
def upgrade() -> None:
    bind = op.get_bind()
    # 直接使用 SQLAlchemy Core，不依赖 ORM 模型
    rows = bind.execute(sa.text("SELECT id, api_key FROM user_llm_providers WHERE api_key != ''"))
    for row in rows:
        if row.api_key and not row.api_key.startswith("gAAAAA"):  # 跳过已加密
            encrypted = encrypt_api_key(row.api_key)
            bind.execute(
                sa.text("UPDATE user_llm_providers SET api_key = :key WHERE id = :id"),
                {"key": encrypted, "id": row.id},
            )
```

**注意：** 迁移脚本中需要独立初始化 Fernet（从环境变量读取 FERNET_KEY），不可依赖 `get_settings()` 避免循环导入。

**Revision chain：** `down_revision` 应设为 `"20260323_0004"`（最后一个线性迁移）或根据实际 head 确定。

---

### 2.7 `.env.example` — 添加 FERNET_KEY

**最近类比：** 同文件 `SECRET_KEY` 条目（L19-20）。

```
# .env.example:19-20
# 生成安全密钥：python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
SECRET_KEY=replace-with-a-secure-random-secret-at-least-32-chars
```

**新增模式：**
```
# 加密密钥（Fernet），用于 API Key 加密存储，丢失不可恢复！请务必备份
# 生成命令：python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY=replace-with-fernet-key
```

---

### 2.8 `docker-compose.yml` — 添加 FERNET_KEY 环境变量

**最近类比：** 同文件 `SECRET_KEY` 的注入模式。

```yaml
# docker-compose.yml:77 (main-service)
- SECRET_KEY=${SECRET_KEY:?SECRET_KEY is required}

# docker-compose.yml:142 (celery-worker)
- SECRET_KEY=${SECRET_KEY:?SECRET_KEY is required}
```

**新增模式：**
- `main-service.environment` 添加 `- FERNET_KEY=${FERNET_KEY:?FERNET_KEY is required}`
- `celery-worker.environment` 添加 `- FERNET_KEY=${FERNET_KEY:?FERNET_KEY is required}`
- 位置：紧接 `SECRET_KEY` 之后

---

### 2.9 `frontend/src/api/providers.ts` — 添加 verifyModel

**最近类比：** 同文件 `fetchModels`（L35-37）。

```typescript
// frontend/src/api/providers.ts:35-37
fetchModels(data: { base_url: string; api_key: string }) {
    return client.post<any, { ok: boolean; models: string[]; error?: string }>('/providers/fetch-models', data)
},
```

**新增模式：**
```typescript
verifyModel(data: { provider_id: string; model: string }) {
    return client.post<any, { ok: boolean; message?: string; error?: string }>('/providers/verify-model', data)
},
```

---

### 2.10 `frontend/src/views/Settings/Account.vue` — 脱敏展示 + 验证按钮

**最近类比（按钮模式）：** 同文件"拉取模型列表"按钮（L299-303）。

```html
<!-- frontend/src/views/Settings/Account.vue:299-303 -->
<Button
  size="sm" variant="outline" class="h-6 px-2 text-[11px]"
  :disabled="p.fetching || !p.base_url"
  @click="fetchModels(p)"
>{{ p.fetching ? '拉取中...' : '拉取模型列表' }}</Button>
```

**最近类比（保存后赋值）：** 同文件 `saveProvider`（L61-76）。

```typescript
// frontend/src/views/Settings/Account.vue:61-76
async function saveProvider(p: ProviderUI) {
  p.saving = true
  p.msg = ''
  try {
    const res = await providersAPI.update(p.id, {
      name: p.name, base_url: p.base_url, api_key: p.api_key,
      models: p.models, format: p.format, is_default: p.is_default,
    })
    Object.assign(p, toUI(res.provider))  // ← 返回的 api_key 已是脱敏值
    p.msg = '已保存'
  } catch (e: any) {
    p.msg = e?.response?.data?.detail || '保存失败'
  } finally {
    p.saving = false
  }
}
```

**新增模式：**
- `ProviderUI` 接口添加 `verifying: boolean` 状态
- 新增 `verifyModel(p, model)` 方法，调用 `providersAPI.verifyModel()`
- 在已选模型列表中每个模型旁添加"验证"小按钮
- `api_key` 输入框的 `placeholder` 改为：保存后显示脱敏值，提示"输入新 Key 可覆盖"

---

## 3. 已确认的项目约定

| 约定 | 来源 | 示例 |
|------|------|------|
| API 响应格式 `{"ok": True/False, ...}` | `providers.py:41,64,84,121,123` | `return {"ok": True, "providers": [...]}` |
| HTTPException 统一错误 | `providers.py:77`, `task_service.py:143` | `raise HTTPException(status_code=404, detail="...")` |
| pydantic-settings + `.env` + `Field(alias=...)` | `config.py:26-36` | `secret_key: str = Field(alias="SECRET_KEY")` |
| `@field_validator` 校验必需安全字段 | `config.py:92-103` | 检查非空、最小长度 |
| 模块级 `settings = get_settings()` | `security.py:17`, `celery_app.py:6` | 模块初始化时获取配置单例 |
| `_serialize()` 函数做对象→字典转换 | `providers.py:17-29` | 集中控制返回字段 |
| docker-compose `${VAR:?required}` 语法 | `docker-compose.yml:77` | 必需变量缺失时报错 |
| Celery task `bind=True` + retry 模式 | `develop_code.py:10` | `@celery_app.task(bind=True, max_retries=3)` |
| `task_db_session()` 上下文管理器 | `_helpers.py:18-27` | Celery 任务中安全创建 DB session |
| Runtime 文件写入 `/tmp/nextproject-task-runtime/{task_id}/` | `task_service.py:556` | 任务级临时文件隔离 |
| 前端 `providersAPI` 对象方法模式 | `providers.ts:18-38` | `client.post<...>(url, data)` |
| 前端 `ProviderUI` 扩展接口 + 状态字段 | `Account.vue:33-39` | `fetching`, `saving`, `msg` 等 UI 状态 |
| Alembic revision 命名 `YYYYMMDD_NNNN_description` | `20260323_0004` | 日期+序号+描述 |

---

## 4. 数据流总览

```
┌─────────────────────────────────────────────────────────────┐
│                       前端 (Account.vue)                     │
│  api_key 输入 ───→ providersAPI.update() ───→ 后端           │
│  保存后收到脱敏值 ←─── {"api_key": "sk-****abcd"} ←─── 后端  │
│  点击"验证" ───→ providersAPI.verifyModel() ───→ 后端        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                  API 层 (providers.py)                        │
│  create/update: encrypt_api_key(raw) → DB                    │
│  _serialize():  decrypt → mask_api_key() → 前端              │
│  update 特殊处理: "****" 检测 → 跳过 api_key 更新            │
│  verify-model: DB → decrypt → httpx 请求外部 API             │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│              服务层 (task_service.py)                         │
│  DB(密文) → decrypt_api_key() → 临时文件(/tmp/.../api_key)   │
│  extra_env 传文件路径 → shell 脚本 cat 读取                   │
│  update_status(终态) → _cleanup_task_runtime()               │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│              任务层 (develop_code.py)                         │
│  acquire_site_lock(site_id) → 成功: 执行 → release           │
│                              → 失败: self.retry(countdown=30)│
└─────────────────────────────────────────────────────────────┘
```

---

*Patterns extracted: 2026-04-23*
*Phase: 01-security-hardening*
