# Phase 01 Verification: 安全加固与基础设施加固

**Verified:** 2026-04-27
**Phase Goal:** 所有凭据加密存储，消除已知安全漏洞，为后续功能提供安全基础。
**Result: PASS — 7/7 需求 ID 全覆盖，48/48 验收标准通过，16/16 must_haves 满足。**

---

## Requirement Traceability

Phase frontmatter 声明的需求 ID 与 REQUIREMENTS.md 定义交叉核对：

| Req ID | REQUIREMENTS.md 定义 | 实现 Plan | 代码证据 | 状态 |
|--------|----------------------|-----------|----------|------|
| SEC-01 | 所有用户凭据（API Key、部署密码）加密存储，不明文落库 | Plan 01-01 | `encrypt_api_key()` 在 create/update 写入；Alembic 迁移现有数据 | PASS |
| SEC-02 | AI 任务执行时通过临时文件传入 API Key，任务结束后删除 | Plan 01-03 | `_write_api_key_file()` 0o600 权限；`_cleanup_task_runtime()` 终态清理 | PASS |
| SEC-03 | 每个仓库的 AI 任务通过 Redis 分布式锁防止并发冲突 | Plan 01-03 | `redis_lock.py`；`develop_code.py` 集成锁 + retry | PASS |
| KEY-01 | 用户可配置自己的 Claude API Key，平台加密存储（Fernet） | Plan 01-01 | `providers.py` create/update 均调用 `encrypt_api_key()` | PASS |
| KEY-02 | 用户可配置自己的 OpenAI API Key，平台加密存储 | Plan 01-01 | 同 KEY-01，format 字段区分 Claude/OpenAI | PASS |
| KEY-03 | 用户配置 API Key 后可验证连通性 | Plan 01-02 | `POST /api/v2/providers/verify-model`；前端验证按钮 | PASS |
| KEY-04 | API Key 在 API 返回时脱敏处理（仅显示末 4 位） | Plan 01-01 | `_serialize()` 中 `mask_api_key(decrypt_api_key(p.api_key))` | PASS |

**Coverage: 7/7 — 100%**

> 注：Plan 01-01、01-02、01-03 的 frontmatter 共同声明了上述全部 7 个 ID，无遗漏，无多余。

---

## Plan 01-01: API Key 加密存储改造

### Acceptance Criteria (15/15 PASS)

| Task | 验收条件 | 代码位置 | 结果 |
|------|----------|----------|------|
| 1.1 | `config.py` 含 `fernet_key: str = Field(alias="FERNET_KEY")` | `backend/core/config.py:36` | PASS |
| 1.1 | `config.py` 含 `def validate_fernet_key` | `backend/core/config.py:108` | PASS |
| 1.1 | `config.py` 含 `len(value) != 44` | `backend/core/config.py:115` | PASS |
| 1.1 | `.env.example` 含 `FERNET_KEY=replace-with-fernet-key` | `.env.example:23` | PASS |
| 1.1 | `.env.example` 含 `丢失不可恢复` | `.env.example:21` | PASS |
| 1.1 | `docker-compose.yml` 含 `FERNET_KEY=...` (2+ 服务) | `docker-compose.yml:78,144` (main-service + celery-worker) | PASS |
| 1.2 | `encryption.py` 存在且含 `from cryptography.fernet import Fernet` | `backend/core/encryption.py:6` | PASS |
| 1.2 | 含 `def encrypt_api_key`, `def decrypt_api_key`, `def mask_api_key`, `def is_masked` | `encryption.py:22,29,43,70` | PASS |
| 1.2 | 含 `def _get_fernet()` 及 `@lru_cache(maxsize=1)` | `encryption.py:11-12` | PASS |
| 1.3 | `providers.py` 导入全部 4 个加密函数 | `providers.py:15` | PASS |
| 1.3 | `_serialize()` 使用 `mask_api_key(decrypt_api_key(p.api_key))` | `providers.py:64` | PASS |
| 1.3 | `create_provider()` 使用 `encrypt_api_key(...)` | `providers.py:97` | PASS |
| 1.3 | `update_provider()` 检查 `is_masked(raw_key)` 并加密新值 | `providers.py:125,127` | PASS |
| 1.4 | Alembic 迁移存在，含 `gAAAAA` 跳过逻辑和 upgrade/downgrade | `20260423_0001_encrypt_api_keys.py:35,27,44` | PASS |
| 1.5 | 前端 placeholder 更新为 `输入新 Key 可覆盖，留空保持不变` | `Account.vue:328` | PASS |

### Must-Haves (5/5 PASS)

- [x] 新写入的 `api_key` 在数据库中是 Fernet 密文（`encrypt_api_key` 在 create/update 均调用）
- [x] API 返回的 `api_key` 始终是脱敏值（`_serialize` 中 `mask_api_key(decrypt_api_key(...))`）
- [x] 更新时包含 `****` 的值被跳过，不覆盖数据库（`is_masked(raw_key)` 检查）
- [x] 现有明文数据通过 Alembic 迁移自动加密（`20260423_0001_encrypt_api_keys.py`）
- [x] FERNET_KEY 通过环境变量配置，main-service 和 celery-worker 均注入（`:?required` 语法）

---

## Plan 01-02: API Key 连通性验证端点

### Acceptance Criteria (18/18 PASS)

| Task | 验收条件 | 代码位置 | 结果 |
|------|----------|----------|------|
| 2.1 | `@router.post("/verify-model")` 端点存在 | `providers.py:150` | PASS |
| 2.1 | `async def verify_model(` 函数签名 | `providers.py:151` | PASS |
| 2.1 | Claude API: `"x-api-key": api_key` header | `providers.py:189` | PASS |
| 2.1 | Claude API: `"anthropic-version": "2023-06-01"` | `providers.py:188` | PASS |
| 2.1 | OpenAI Responses: `f"{base_url}/responses"` | `providers.py:200` | PASS |
| 2.1 | OpenAI Chat: `f"{base_url}/chat/completions"` | `providers.py:214` | PASS |
| 2.1 | Claude Messages: `f"{base_url}/messages"` | `providers.py:185` | PASS |
| 2.1 | 最小请求: `"max_tokens": 5` | `providers.py` | PASS |
| 2.1 | 服务端解密: `decrypt_api_key(p.api_key)` | `providers.py` | PASS |
| 2.1 | SSRF 防护: base_url 协议 + 内网地址校验 | `providers.py:21-54` (超出 Plan 要求，实现更强) | PASS |
| 2.2 | `providers.ts` 含 `verifyModel` 方法 | `providers.ts:39` | PASS |
| 2.2 | 路由 `'/providers/verify-model'` | `providers.ts:40` | PASS |
| 2.3 | `ProviderUI` 含 `verifying: string` 字段 | `Account.vue:39` | PASS |
| 2.3 | `toUI` 初始化 `verifying: ''` | `Account.vue:45` | PASS |
| 2.3 | `async function verifyModel(p: ProviderUI, model: string)` | `Account.vue:124` | PASS |
| 2.3 | `providersAPI.verifyModel(...)` 调用（传入 provider_id + model）| `Account.vue:132` | PASS |
| 2.3 | `连通正常` 成功消息 | `Account.vue:133` | PASS |
| 2.3 | `@click.stop="verifyModel(p, m)"` 事件处理 | `Account.vue:365` | PASS |

> **超出 Plan 的实现：** SSRF 防护除协议校验外，还增加了内网/私有网络地址过滤（`_validate_url_ssrf` 函数），安全等级高于 Plan 要求。

### Must-Haves (5/5 PASS)

- [x] `POST /api/v2/providers/verify-model` 端点存在，接受 `provider_id` 和 `model`
- [x] 支持三种 API 格式：`messages`（Claude）、`responses`（OpenAI Responses）、`chat/completions`（OpenAI Chat）
- [x] Key 从数据库解密读取，前端不传明文 API Key
- [x] 前端已选模型旁有"验证"按钮，点击后显示成功/失败结果
- [x] `base_url` 协议校验（仅允许 http/https），且额外过滤内网地址

---

## Plan 01-03: AI 任务安全执行机制

### Acceptance Criteria (15/15 PASS)

| Task | 验收条件 | 代码位置 | 结果 |
|------|----------|----------|------|
| 3.1 | `redis_lock.py` 存在且含 `import redis` | `backend/core/redis_lock.py` | PASS |
| 3.1 | `_LOCK_PREFIX = "nextproject:site-lock:"` | `redis_lock.py:8` | PASS |
| 3.1 | `acquire_site_lock` 和 `release_site_lock` 函数 | `redis_lock.py:26,32` | PASS |
| 3.1 | `_RELEASE_SCRIPT` Lua 脚本 + `r.eval()` 调用 | `redis_lock.py:12,35` | PASS |
| 3.1 | `nx=True, ex=ttl` 在 SET 命令中 | `redis_lock.py:29` | PASS |
| 3.2 | `develop_code.py` 导入 `acquire_site_lock, release_site_lock` | `develop_code.py:6` | PASS |
| 3.2 | `from backend.models import Task`（普通导入） | `develop_code.py:7` | PASS |
| 3.2 | `max_retries=60, default_retry_delay=30` | `develop_code.py:12` | PASS |
| 3.2 | `acquire_site_lock(site_id, task_id)` + `self.retry(countdown=30)` | `develop_code.py:22-23` | PASS |
| 3.2 | `release_site_lock` 在 `finally` 块中 | `develop_code.py:29-30` | PASS |
| 3.2 | 无 `__import__` 动态导入 | `develop_code.py`（确认不含） | PASS |
| 3.3 | `decrypt_api_key` 导入并使用 | `task_service.py:23, 622` | PASS |
| 3.3 | `_write_api_key_file` 含 `0o600` 权限设置 | `task_service.py:99,104` | PASS |
| 3.3 | `_cleanup_task_runtime` 含 `shutil.rmtree` | `task_service.py:108,112` | PASS |
| 3.3 | `CODEX_TASK_API_KEY_FILE` 替换旧 `CODEX_TASK_API_KEY` 环境变量 | `task_service.py:626`（旧模式已确认移除） | PASS |

### Must-Haves (6/6 PASS)

- [x] Codex API Key 通过临时文件传入（`CODEX_TASK_API_KEY_FILE`），不再出现在 `CODEX_TASK_API_KEY` 环境变量中
- [x] 临时文件权限为 `0o600`（`stat.S_IRUSR | stat.S_IWUSR`）
- [x] 任务完成/失败/取消后 runtime 目录被清理（`_cleanup_task_runtime` 在终态触发）
- [x] 同一 site 的 AI 任务通过 Redis 分布式锁串行执行，第二个任务 retry 等待
- [x] 锁释放使用 Lua 脚本校验持有者，防止误释放
- [x] `claude_code` provider 使用 `ANTHROPIC_API_KEY` 环境变量已记录为 Accepted Risk（`task_service.py:651`）

---

## Summary

| 指标 | 值 |
|------|----|
| 需求 ID 覆盖率 | 7/7 (100%) |
| Plan 完成数 | 3/3 |
| 验收标准通过 | 48/48 |
| Must-haves 满足 | 16/16 |
| 失败项 | 0 |
| 超出 Plan 的实现 | 1（SSRF 防护增加了内网地址过滤） |

**Phase 01 目标达成：所有凭据加密存储，已知安全漏洞已消除，安全基础已就绪。**
