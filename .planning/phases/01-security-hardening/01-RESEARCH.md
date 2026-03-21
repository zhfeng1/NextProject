# Phase 1: 安全加固与基础设施加固 - Research

**Date:** 2026-04-23
**Status:** Complete

## 1. 现有代码现状分析

### 1.1 API Key 存储现状（当前安全风险）

- **模型定义** `backend/models/user_llm_provider.py:17` — `api_key` 字段为 `Text` 类型，明文存储
- **CRUD 端点** `backend/api/v2/providers.py` — `_serialize()` (L17-29) 直接返回 `p.api_key` 明文
- **创建端点** `providers.py:56` — 明文写入 `api_key`
- **更新端点** `providers.py:79-81` — `api_key` 在 `allowed` 字段集中，直接 setattr 明文
- **任务执行** `backend/services/task_service.py:592-596` — 直接读取 `llm_provider.api_key` 明文设置为环境变量
- **前端** `frontend/src/views/Settings/Account.vue:305` — `<Input type="password">` 仅为前端视觉遮挡，API 层无脱敏

### 1.2 任务并发现状

- **Celery 配置** `backend/core/celery_app.py` — 无锁机制，`worker_prefetch_multiplier=4`，同仓库可能并发执行
- **任务入队** `task_service.py:292-307` — `enqueue_task()` 直接 `delay()`，无锁检查
- **环境变量传递** `task_service.py:594-596` — API Key 通过 `extra_env` 直接传入子进程环境变量

### 1.3 已有可复用资产

| 资产 | 位置 | 用途 |
|------|------|------|
| `cryptography` 包 | `requirements.txt:16` via `python-jose[cryptography]` | Fernet 加密直接可用，无需新增依赖 |
| pydantic-settings | `backend/core/config.py` | 添加 `FERNET_KEY` 配置项 |
| security 模块 | `backend/core/security.py` | 放置加解密工具函数 |
| Alembic data migration | `backend/alembic/` | 迁移明文→密文 |
| Redis | `celery_app.py` + `docker-compose.yml` | 分布式锁基础设施 |
| httpx | `providers.py:102-123` | `fetch-models` 已有外部 API 调用模式 |
| `{"ok": True/False}` | 全局 API 响应格式 | 验证端点保持一致 |

---

## 2. 技术方案详细研究

### 2.1 Fernet 加密方案

**选型理由：** `cryptography.fernet.Fernet` 是对称加密标准方案，已通过 `python-jose[cryptography]` 间接安装。

**关键实现点：**

```python
from cryptography.fernet import Fernet

# 密钥生成（一次性，存入 .env）
key = Fernet.generate_key()  # bytes, base64 编码的 32 字节密钥

# 加密/解密
f = Fernet(key)
encrypted = f.encrypt(plaintext.encode())  # bytes → bytes (base64)
decrypted = f.decrypt(encrypted).decode()  # bytes → str
```

**注意事项：**
- Fernet 输出是 base64 编码文本，存入 `Text` 字段无需改列类型
- Fernet 密文包含时间戳，同一明文每次加密结果不同（安全）
- 密钥丢失 = 所有 API Key 不可恢复，**必须提醒用户备份 FERNET_KEY**
- 空字符串 api_key 不加密（兼容无 Key 场景如本地 Ollama）

### 2.2 配置变更

`backend/core/config.py` 需添加：

```python
fernet_key: str = Field(alias="FERNET_KEY")
```

需同步更新：
- `.env.example` — 添加 `FERNET_KEY` 及生成命令注释
- `docker-compose.yml` — `main-service` 和 `celery-worker` 的 environment 中添加 `FERNET_KEY`

**密钥生成命令：**
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2.3 加解密工具模块

在 `backend/core/security.py` 或新建 `backend/core/encryption.py` 中添加：

```python
def encrypt_api_key(plaintext: str) -> str:
    """加密 API Key，空值原样返回"""

def decrypt_api_key(ciphertext: str) -> str:
    """解密 API Key，空值原样返回"""

def mask_api_key(key: str) -> str:
    """脱敏显示：sk-****abcd 或 ****abcd"""
```

**集成点：**
1. `providers.py` create/update — 写入前调用 `encrypt_api_key()`
2. `providers.py` `_serialize()` — 返回时调用 `mask_api_key()`
3. `task_service.py:592` — 读取后调用 `decrypt_api_key()` 获取明文用于任务执行

### 2.4 Alembic 数据迁移

新建 migration 文件，upgrade 时：
1. 查询所有 `user_llm_providers` 行
2. 对非空 `api_key` 调用 `encrypt_api_key()`
3. 批量 UPDATE 回写

**注意：** Alembic data migration 需要使用同步引擎（`resolved_sync_database_url`），参考 `env.py` 现有模式。迁移脚本不可依赖 ORM 模型。

**迁移安全：**
- 已加密的数据（以 `gAAAAA` 开头的 Fernet token）需跳过，防止重复加密
- downgrade 需保留解密能力（或标记为不可逆）

### 2.5 API 脱敏格式

决策 D-04：`sk-****abcd`（保留前缀 + 末 4 位）

```python
def mask_api_key(key: str) -> str:
    if not key or key.startswith("****"):
        return key  # 已脱敏或空
    prefix = ""
    if "-" in key[:10]:
        prefix = key[:key.index("-") + 1]  # "sk-"
    suffix = key[-4:]
    return f"{prefix}****{suffix}"
```

**影响端点：**
- `GET /api/v2/providers` — list
- `POST /api/v2/providers` — create
- `PUT /api/v2/providers/{id}` — update

**前端影响：**
- `Account.vue` 中 `api_key` 输入框：保存后返回的是脱敏值
- 用户如果不修改 Key，前端发送脱敏值回来，后端需判断是否是脱敏值（包含 `****`），如果是则不更新 api_key 字段

### 2.6 模型连通性验证端点

决策 D-06~D-09：验证**模型可用性**（非单纯 Key 验证），支持三种 API 格式。

**新增端点：** `POST /api/v2/providers/verify-model`

**请求体：**
```json
{
  "provider_id": "uuid",       // 可选，从已保存的 provider 读取配置
  "base_url": "https://...",   // 或直接传
  "api_key": "sk-...",
  "model": "gpt-4o",
  "format": "responses"        // responses | messages | completions
}
```

**三种 API 格式的验证请求：**

| 格式 | 端点 | 请求体 |
|------|------|--------|
| `completions` | `{base_url}/chat/completions` | `{"model": "...", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}` |
| `responses` | `{base_url}/responses` | `{"model": "...", "input": "hi", "max_output_tokens": 5}` |
| `messages` | `{base_url}/messages` | `{"model": "...", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}` + `x-api-key` header + `anthropic-version: 2023-06-01` header |

**关键差异：**
- Claude API 使用 `x-api-key` header（非 `Authorization: Bearer`）
- Claude API 需要 `anthropic-version` header
- OpenAI Responses API 是新格式，路径为 `/responses`
- 超时设置 10 秒（轻量请求不需要太久）

**响应格式：**
```json
{"ok": true, "message": "模型 gpt-4o 连通正常"}
{"ok": false, "error": "401 Unauthorized: Invalid API key"}
```

**前端改动：**
- `Account.vue` 中每个 provider 的模型列表旁添加"验证"按钮
- `providers.ts` 添加 `verifyModel()` API 方法

### 2.7 临时文件传入 API Key

**当前问题：** `task_service.py:594` 直接将 `api_key` 设为环境变量，`/proc/<pid>/environ` 可见。

**改造方案：**
1. 将 API Key 写入临时文件 `/tmp/nextproject-task-runtime/{task_id}/api_key`，权限 `0o600`
2. 环境变量改为传文件路径：`CODEX_TASK_API_KEY_FILE=/tmp/.../api_key`
3. Shell 脚本中改为从文件读取：`$(cat "$CODEX_TASK_API_KEY_FILE")`
4. 对于 `claude_code` provider：使用 `ANTHROPIC_API_KEY_FILE` 或启动前从文件读取设为环境变量
5. 任务完成后（成功/失败/取消）清理 `/tmp/nextproject-task-runtime/{task_id}/` 目录

**具体改动点：**
- `task_service.py` 的 `_run_develop_task_for_provider()` 方法（L479+）
- Codex 的 shell 命令构建（L599-615）— 修改 `sh -lc` 内的脚本，从文件读取 Key
- Claude Code 的环境变量设置（L619-621）— 改为写文件 + 从文件 source

**清理时机：**
- `update_status()` 中当 status 为 SUCCESS/FAILED/CANCELED 时，清理对应 task 的 runtime 目录
- 添加 `_cleanup_task_runtime(task_id)` 方法

### 2.8 Redis 分布式锁

**需求：** 同一仓库（site_id）同时只允许一个 AI 任务执行，其他任务排队。

**方案选型：** 使用 Redis `SET NX EX` 实现简单分布式锁，不需要 Redlock（单 Redis 实例）。

**锁键格式：** `nextproject:site-lock:{site_id}`
**锁 TTL：** 与 `default_task_timeout_seconds`（1800s）一致 + 额外裕量

**实现方式（两种选择）：**

**方案 A — Celery 任务内获取锁 + 自旋等待：**
```python
@celery_app.task(bind=True, max_retries=60, default_retry_delay=30)
def develop_code_task(self, task_id):
    # 尝试获取锁，失败则 retry（Celery 内置重试机制）
    if not acquire_lock(site_id):
        raise self.retry(countdown=30)
    try:
        run_task()
    finally:
        release_lock(site_id)
```

**方案 B — 提交时检查 + Celery ETA 延迟：**
- `create_task()` 时检查锁状态，设置 Celery task 的 `eta` 参数延迟执行

**推荐方案 A**，理由：
- 与 Celery 重试机制天然契合
- 不需要预测前一个任务何时完成
- 实现简单，锁释放后下一次 retry 自动获取

**锁的持有者标识：** `task_id`（用于释放时校验）

**工具函数：**
```python
import redis

def acquire_site_lock(redis_client, site_id: str, task_id: str, ttl: int = 2100) -> bool:
    return redis_client.set(f"nextproject:site-lock:{site_id}", task_id, nx=True, ex=ttl)

def release_site_lock(redis_client, site_id: str, task_id: str) -> bool:
    # Lua 脚本：只有持有者可以释放
    script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
    return redis_client.eval(script, 1, f"nextproject:site-lock:{site_id}", task_id)
```

**Redis 客户端获取：** 复用 Celery 的 Redis 连接（`settings.redis_url`）。

---

## 3. 变更影响分析

### 3.1 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/core/config.py` | 修改 | 添加 `fernet_key` 字段 |
| `backend/core/security.py` 或新建 `encryption.py` | 新建/修改 | 加密/解密/脱敏工具函数 |
| `backend/api/v2/providers.py` | 修改 | `_serialize()` 脱敏、create/update 加密、新增 verify-model 端点、更新时跳过脱敏值 |
| `backend/services/task_service.py` | 修改 | 解密 Key → 临时文件、锁机制集成、runtime 清理 |
| `backend/tasks/develop_code.py` | 修改 | 锁获取/释放逻辑 |
| `backend/alembic/versions/xxxx_encrypt_api_keys.py` | 新建 | 数据迁移 |
| `.env.example` | 修改 | 添加 FERNET_KEY |
| `docker-compose.yml` | 修改 | main-service + celery-worker 添加 FERNET_KEY 环境变量 |
| `frontend/src/api/providers.ts` | 修改 | 添加 `verifyModel()` 方法 |
| `frontend/src/views/Settings/Account.vue` | 修改 | 添加验证按钮、处理脱敏 api_key 显示 |

### 3.2 不需要新增依赖

`cryptography` 已通过 `python-jose[cryptography]` 安装，Fernet 可直接使用。Redis 已在架构中。

### 3.3 数据库变更

- 列类型不变（`api_key` 保持 `Text`）
- 仅需 data migration（明文→密文）
- 无 schema migration

### 3.4 前端兼容性注意点

- **脱敏值回传问题：** 保存 provider 时，如果 `api_key` 包含 `****`，说明用户未修改 Key，后端应跳过 api_key 字段更新
- **验证按钮：** 需在已保存的 provider 上操作（使用 `provider_id` 调后端，由后端解密 Key 发请求），避免前端持有明文

---

## 4. 风险与注意事项

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| FERNET_KEY 丢失导致所有 Key 不可恢复 | **高** | 文档明确提醒备份；生成脚本在 .env.example 注释中 |
| 迁移脚本在大量数据时性能 | 低 | 当前用户量小，逐行加密即可 |
| Celery retry 导致任务长时间排队 | 中 | 设置 max_retries 上限 + 前端展示"等待中"状态 |
| 临时文件清理遗漏（容器崩溃） | 低 | /tmp 目录容器重启自动清理；可加定期清理 |
| 验证端点被滥用刷 API 额度 | 低 | 使用 `max_tokens=5` 的最小请求；受 JWT 认证保护 |
| 脱敏值误写入数据库 | 中 | 后端 update 逻辑严格检查 `****` 模式 |

---

## 5. 三个 Plan 的建议执行顺序

1. **Plan 1: API Key 加密存储改造** — 基础设施，其他两个 Plan 依赖
2. **Plan 2: API Key 连通性验证端点** — 依赖 Plan 1 的加密/解密函数
3. **Plan 3: AI 任务安全执行机制** — 依赖 Plan 1 的解密函数 + 独立的锁机制

Plan 2 和 Plan 3 理论上可并行实施（各自依赖 Plan 1 的加密模块，但互相不依赖）。

---

*Research completed: 2026-04-23*
*Phase: 01-security-hardening*
