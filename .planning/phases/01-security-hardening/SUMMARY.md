# Plan 01-01 Summary: API Key 加密存储改造

## Status: COMPLETED

## Tasks Completed

### Task 1.1: 添加 FERNET_KEY 配置项
- Added `fernet_key: str = Field(alias="FERNET_KEY")` to Settings class in `backend/core/config.py`
- Added `validate_fernet_key` validator with 44-char length check
- Added FERNET_KEY entry with generation instructions to `.env.example`
- Injected FERNET_KEY into main-service, celery-worker (required), and test (default value) in `docker-compose.yml`
- **Commit:** `dd3a95c`

### Task 1.2: 创建加密工具模块 encryption.py
- Created `backend/core/encryption.py` with:
  - `_get_fernet()` — lazy-cached Fernet instance via `@lru_cache(maxsize=1)`
  - `encrypt_api_key()` — encrypts plaintext to Fernet ciphertext
  - `decrypt_api_key()` — decrypts ciphertext back to plaintext
  - `mask_api_key()` — masks keys for display (e.g., `sk-****abcd`)
  - `is_masked()` — detects masked values containing `****`
- **Commit:** `5619b42`

### Task 1.3: 改造 providers.py
- `_serialize()` now decrypts then masks API keys before returning
- `create_provider()` encrypts API key before database storage
- `update_provider()` skips api_key update if value is masked or empty, encrypts new values
- **Commit:** `9d647a9`

### Task 1.4: Alembic 数据迁移
- Created `backend/alembic/versions/20260423_0001_encrypt_api_keys.py`
- Upgrade: encrypts all plaintext api_key values, skips rows with `gAAAAA` prefix
- Downgrade: decrypts ciphertext back to plaintext
- Requires FERNET_KEY environment variable
- **Commit:** `d240790`

### Task 1.5: 前端适配
- Updated API Key input placeholder to `"输入新 Key 可覆盖，留空保持不变"`
- Backend masked values flow through naturally via existing `Object.assign` pattern
- **Commit:** `0ccf9c2`

## Verification
All 15 acceptance criteria checks passed.

## Files Modified
- `backend/core/config.py` — FERNET_KEY field + validator
- `backend/core/encryption.py` — new file, encryption utilities
- `backend/api/v2/providers.py` — encrypt on write, mask on read
- `backend/alembic/versions/20260423_0001_encrypt_api_keys.py` — new file, data migration
- `.env.example` — FERNET_KEY placeholder + instructions
- `docker-compose.yml` — FERNET_KEY environment injection (3 services)
- `frontend/src/views/Settings/Account.vue` — placeholder text update

---

# Plan 01-02 Summary: API Key 连通性验证端点

## Status: COMPLETED

## Tasks Completed

### Task 2.1: 新增 verify-model 后端端点
- Added `POST /providers/verify-model` endpoint to `backend/api/v2/providers.py`
- Supports three API formats: Messages (Claude), Responses (OpenAI), Chat Completions (fallback)
- Key decrypted server-side via `decrypt_api_key()` — never sent from frontend
- SSRF mitigation: rejects `base_url` with non-http(s) schemes
- Lightweight request: `max_tokens=5` with "hi" input
- **Commit:** `dd12033`

### Task 2.2: 前端添加 verifyModel API 方法
- Added `verifyModel()` method to `providersAPI` object in `frontend/src/api/providers.ts`
- Accepts `{ provider_id, model }` and returns `{ ok, message?, error? }`
- **Commit:** `467a10e`

### Task 2.3: 前端在已选模型旁添加验证按钮
- Added `verifying: string` field to `ProviderUI` interface
- Added `verifyModel()` async function for triggering verification
- Added "验证" button next to each selected model in the template
- Button shows "..." while verifying, disabled during request
- Success/failure message displayed in provider card footer
- **Commit:** `631d02e`

## Verification
All 18 acceptance criteria checks passed.

## Files Modified
- `backend/api/v2/providers.py` — new verify-model endpoint (83 lines added)
- `frontend/src/api/providers.ts` — verifyModel API method
- `frontend/src/views/Settings/Account.vue` — verifying state, verifyModel function, verify button UI
