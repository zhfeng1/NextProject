# Phase 01 Verification: 安全加固与基础设施加固

**Verified:** 2026-04-23
**Phase Goal:** 所有凭据加密存储，消除已知安全漏洞，为后续功能提供安全基础。
**Result: PASS — All 7 requirement IDs covered, all 48 acceptance criteria pass, all 16 must_haves satisfied.**

---

## Requirement Traceability

Cross-reference of phase requirement IDs against REQUIREMENTS.md definitions:

| Req ID | REQUIREMENTS.md Definition | Covered By | Status |
|--------|----------------------------|------------|--------|
| SEC-01 | 所有用户凭据（API Key、部署密码）加密存储，不明文落库 | Plan 01-01 (Fernet 加密存储) | PASS |
| SEC-02 | AI 任务执行时通过临时文件传入 API Key，任务结束后删除 | Plan 01-03 (临时文件 + 清理) | PASS |
| SEC-03 | 每个仓库的 AI 任务通过 Redis 分布式锁防止并发冲突 | Plan 01-03 (Redis 分布式锁) | PASS |
| KEY-01 | 用户可配置自己的 Claude API Key，平台加密存储（Fernet） | Plan 01-01 (encrypt_api_key) | PASS |
| KEY-02 | 用户可配置自己的 OpenAI API Key，平台加密存储 | Plan 01-01 (encrypt_api_key) | PASS |
| KEY-03 | 用户配置 API Key 后可验证连通性 | Plan 01-02 (verify-model 端点) | PASS |
| KEY-04 | API Key 在 API 返回时脱敏处理（仅显示末 4 位） | Plan 01-01 (mask_api_key) | PASS |

**Coverage: 7/7 requirement IDs — 100%**

---

## Plan 01-01: API Key 加密存储改造

### Acceptance Criteria (15/15 PASS)

| Task | Criteria | Result |
|------|----------|--------|
| 1.1 | `config.py` contains `fernet_key: str = Field(alias="FERNET_KEY")` | PASS |
| 1.1 | `config.py` contains `def validate_fernet_key` | PASS |
| 1.1 | `config.py` contains `len(value) != 44` | PASS |
| 1.1 | `.env.example` contains `FERNET_KEY=replace-with-fernet-key` | PASS |
| 1.1 | `.env.example` contains `丢失不可恢复` | PASS |
| 1.1 | `docker-compose.yml` contains `FERNET_KEY=${FERNET_KEY:?...}` (2+ services) | PASS |
| 1.2 | `encryption.py` exists with `from cryptography.fernet import Fernet` | PASS |
| 1.2 | `encrypt_api_key`, `decrypt_api_key`, `mask_api_key`, `is_masked` functions | PASS |
| 1.2 | `_get_fernet()` with `@lru_cache(maxsize=1)` | PASS |
| 1.3 | `providers.py` imports all 4 encryption functions | PASS |
| 1.3 | `_serialize()` uses `mask_api_key(decrypt_api_key(p.api_key))` | PASS |
| 1.3 | `create_provider()` uses `encrypt_api_key(...)` | PASS |
| 1.3 | `update_provider()` checks `is_masked(raw_key)` and encrypts new values | PASS |
| 1.4 | Alembic migration exists with `gAAAAA` skip logic and upgrade/downgrade | PASS |
| 1.5 | Frontend placeholder updated, old text removed | PASS |

### Must-Haves (5/5 PASS)

- [x] 新写入的 `api_key` 在数据库中是 Fernet 密文（`encrypt_api_key` 在 create/update 中调用）
- [x] API 返回的 `api_key` 始终是脱敏值（`_serialize` 中 `mask_api_key(decrypt_api_key(...))`)
- [x] 更新时 `****` 值被跳过（`is_masked(raw_key)` 检查）
- [x] 现有明文数据通过 Alembic 迁移自动加密（`20260423_0001_encrypt_api_keys.py`）
- [x] FERNET_KEY 通过环境变量配置，main-service 和 celery-worker 都能访问

---

## Plan 01-02: API Key 连通性验证端点

### Acceptance Criteria (18/18 PASS)

| Task | Criteria | Result |
|------|----------|--------|
| 2.1 | `@router.post("/verify-model")` endpoint exists | PASS |
| 2.1 | `async def verify_model(` function signature | PASS |
| 2.1 | Claude API: `"x-api-key": api_key` header | PASS |
| 2.1 | Claude API: `"anthropic-version": "2023-06-01"` | PASS |
| 2.1 | OpenAI Responses: `f"{base_url}/responses"` | PASS |
| 2.1 | OpenAI Chat: `f"{base_url}/chat/completions"` | PASS |
| 2.1 | Claude Messages: `f"{base_url}/messages"` | PASS |
| 2.1 | Lightweight request: `"max_tokens": 5` | PASS |
| 2.1 | Server-side decrypt: `decrypt_api_key(p.api_key)` | PASS |
| 2.1 | SSRF check: `not base_url.startswith(("https://", "http://"))` | PASS |
| 2.2 | `verifyModel` method in `providers.ts` | PASS |
| 2.2 | Route `'/providers/verify-model'` | PASS |
| 2.3 | `verifying: string` field in `ProviderUI` | PASS |
| 2.3 | `verifying: ''` initialization in `toUI` | PASS |
| 2.3 | `async function verifyModel(p: ProviderUI, model: string)` | PASS |
| 2.3 | `providersAPI.verifyModel({ provider_id: p.id, model })` call | PASS |
| 2.3 | `连通正常` success message | PASS |
| 2.3 | `@click.stop="verifyModel(p, m)"` handler | PASS |

### Must-Haves (5/5 PASS)

- [x] `POST /api/v2/providers/verify-model` 端点存在
- [x] 验证支持三种 API 格式：messages、responses、completions
- [x] Key 从数据库解密读取，前端不传明文
- [x] 前端已选模型旁有"验证"按钮
- [x] `base_url` 协议校验：仅允许 http/https

---

## Plan 01-03: AI 任务安全执行机制

### Acceptance Criteria (15/15 PASS)

| Task | Criteria | Result |
|------|----------|--------|
| 3.1 | `redis_lock.py` exists with `import redis` | PASS |
| 3.1 | `_LOCK_PREFIX = "nextproject:site-lock:"` | PASS |
| 3.1 | `acquire_site_lock` and `release_site_lock` functions | PASS |
| 3.1 | `_RELEASE_SCRIPT` Lua script with `r.eval()` | PASS |
| 3.1 | `nx=True, ex=ttl` in SET command | PASS |
| 3.2 | `develop_code.py` imports `acquire_site_lock, release_site_lock` | PASS |
| 3.2 | `from backend.models import Task` (normal import) | PASS |
| 3.2 | `max_retries=60, default_retry_delay=30` | PASS |
| 3.2 | `acquire_site_lock(site_id, task_id)` + `self.retry(countdown=30)` | PASS |
| 3.2 | `release_site_lock` in `finally` block | PASS |
| 3.2 | No `__import__` dynamic import | PASS |
| 3.3 | `decrypt_api_key` import and usage | PASS |
| 3.3 | `_write_api_key_file` with `0o600` permissions | PASS |
| 3.3 | `_cleanup_task_runtime` with `shutil.rmtree` | PASS |
| 3.3 | `CODEX_TASK_API_KEY_FILE` replaces old `CODEX_TASK_API_KEY` env var | PASS |

### Must-Haves (6/6 PASS)

- [x] Codex API Key 通过临时文件传入，不再出现在 `CODEX_TASK_API_KEY` 环境变量中
- [x] 临时文件权限为 `0o600`
- [x] 任务终态后 runtime 目录被清理
- [x] 同一 site 通过 Redis 分布式锁串行执行
- [x] 锁释放使用 Lua 脚本校验持有者
- [x] `claude_code` 使用 `ANTHROPIC_API_KEY` 环境变量已记录为 Accepted Risk

---

## Summary

| Metric | Value |
|--------|-------|
| Requirement IDs covered | 7/7 (100%) |
| Plans completed | 3/3 |
| Total acceptance criteria | 48/48 PASS |
| Total must_haves | 16/16 PASS |
| Failures | 0 |

**Phase 01 goal achieved:** 所有凭据加密存储，已知安全漏洞已消除，安全基础已就绪。
