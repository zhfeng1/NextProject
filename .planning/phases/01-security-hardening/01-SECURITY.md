---
threats_total: 18
threats_closed: 14
threats_open: 0
threats_accepted: 4
---

# Phase 01 Security Hardening — Security Audit Report

## Threat Register

| ID | Category | Component | Severity | Disposition | Status | Evidence |
|----|----------|-----------|----------|-------------|--------|----------|
| T1-01 | Data-at-Rest | `user_llm_providers.api_key` | HIGH | Mitigated | CLOSED | `backend/core/encryption.py:22-26` — `encrypt_api_key()` wraps Fernet; `backend/api/v2/providers.py:57` — `encrypt_api_key()` called on create; `backend/alembic/versions/20260423_0001_encrypt_api_keys.py:35-41` — migration encrypts existing rows |
| T2-01 | Data Exposure | `backend/api/v2/providers.py:_serialize()` | HIGH | Mitigated | CLOSED | `backend/api/v2/providers.py:24` — `mask_api_key(decrypt_api_key(p.api_key))` ensures API responses contain only masked values like `sk-****abcd` |
| T3-01 | Key Management | FERNET_KEY | HIGH | Mitigated | CLOSED | `backend/core/config.py:36` — `fernet_key: str = Field(alias="FERNET_KEY")`; `docker-compose.yml:78` — `FERNET_KEY=${FERNET_KEY:?FERNET_KEY is required}` for main-service; `docker-compose.yml:144` — same for celery-worker; key never appears in source code |
| T4-01 | Data Integrity | `update_provider()` | MEDIUM | Mitigated | CLOSED | `backend/api/v2/providers.py:85` — `if not raw_key or is_masked(raw_key): continue` skips masked `****` values; `backend/core/encryption.py:51-53` — `is_masked()` detects `****` pattern |
| T5-01 | Key Management | FERNET_KEY backup | MEDIUM | Mitigated | CLOSED | `.env.example:21` — comment `"丢失不可恢复！请务必备份"`; `backend/core/config.py:106-117` — `validate_fernet_key()` rejects empty/placeholder values and validates 44-char length |
| T6-01 | Data Integrity | Migration script | LOW | Mitigated | CLOSED | `backend/alembic/versions/20260423_0001_encrypt_api_keys.py:35` — `if api_key.startswith("gAAAAA"): continue` skips already-encrypted rows |
| T1-02 | Resource Abuse | `verify-model` endpoint | LOW | Mitigated | CLOSED | `backend/api/v2/providers.py:149` — `"max_tokens": 5`; endpoint requires JWT auth via `Depends(get_current_user)` at line 113 |
| T2-02 | Data Exposure | Verification request headers | MEDIUM | Mitigated | CLOSED | `backend/api/v2/providers.py:136` — uses `httpx.AsyncClient` (no default header logging); key decrypted server-side at line 132 `decrypt_api_key(p.api_key)`, never received from frontend |
| T3-02 | SSRF | `base_url` in verify-model | MEDIUM | Accepted | ACCEPTED | `backend/api/v2/providers.py:129` — `if base_url and not base_url.startswith(("https://", "http://"))` rejects non-http(s) schemes. Internal network access accepted for Ollama/vLLM use cases |
| T1-03 | Data Exposure | `/proc/environ` API Key | HIGH | Partial/Accepted | CLOSED | Codex: `backend/services/task_service.py:620` — `CODEX_TASK_API_KEY_FILE` file path in env, not the key itself; key read via `cat "${CODEX_TASK_API_KEY_FILE}"` at line 636. Claude Code: `backend/services/task_service.py:648` — `ANTHROPIC_API_KEY = decrypted_key` in env (Accepted Risk — CLI limitation, see T1-03-AR below) |
| T2-03 | File Permissions | Temp API key file | MEDIUM | Mitigated | CLOSED | `backend/services/task_service.py:104` — `key_path.chmod(stat.S_IRUSR \| stat.S_IWUSR)` sets `0o600` permissions |
| T3-03 | Data Residual | Temp file cleanup | MEDIUM | Mitigated | CLOSED | `backend/services/task_service.py:108-115` — `_cleanup_task_runtime()` uses `shutil.rmtree()`; called at line 255 in `update_status()` for terminal states (SUCCESS/FAILED/CANCELED); `backend/tasks/develop_code.py:29-30` — `finally: release_site_lock()` ensures cleanup path is reached |
| T4-03 | Concurrency | Parallel AI task file conflict | HIGH | Mitigated | CLOSED | `backend/core/redis_lock.py:26-29` — `acquire_site_lock()` uses `r.set(..., nx=True, ex=ttl)` per site_id; `backend/tasks/develop_code.py:22-23` — lock acquired before execution, failure triggers `self.retry(countdown=30)` |
| T5-03 | Availability | Lock holder crash deadlock | MEDIUM | Mitigated | CLOSED | `backend/core/redis_lock.py:9` — `_DEFAULT_TTL = 2100` (task timeout 1800s + 300s margin); Redis auto-expires the key |
| T6-03 | Concurrency | Non-holder lock release | LOW | Mitigated | CLOSED | `backend/core/redis_lock.py:12-18` — Lua `_RELEASE_SCRIPT` verifies `redis.call('get', KEYS[1]) == ARGV[1]` (task_id match) before `del`; invoked at line 35 via `r.eval()` |
| T1-03-AR | Data Exposure | Claude CLI env var | HIGH | Accepted | ACCEPTED | `backend/services/task_service.py:644-648` — documented comment: "Accepted Risk: Claude CLI only supports ANTHROPIC_API_KEY env var, no file-based alternative exists. The env var is scoped to the short-lived Celery worker subprocess and destroyed on completion." |
| T-AR-01 | Infrastructure | FERNET_KEY on compromised server | HIGH | Accepted | ACCEPTED | Documented in 01-01-PLAN.md Accepted Risks: "FERNET_KEY 存储在服务器环境变量中，服务器被完全攻陷时 Key 可被提取（属于基础设施安全范畴，非应用层能解决）" |
| T-AR-02 | Data Exposure | Temp file plaintext on disk | MEDIUM | Accepted | ACCEPTED | Documented in 01-03-PLAN.md Accepted Risks: "临时文件在磁盘上短暂存在明文 Key（与写入环境变量相比已大幅降低风险面，服务器 root 权限攻击属于基础设施层面）" |

## Accepted Risks

### AR-1: SSRF via user-configured base_url (T3-02)
- **Severity**: MEDIUM
- **Justification**: Users may legitimately use internal addresses for self-hosted models (Ollama, vLLM). Protocol validation (http/https only) is enforced. Blocking internal IPs would break core functionality.
- **Controls**: HTTP(S) scheme check at `backend/api/v2/providers.py:129`; Docker network isolation limits reachable targets.

### AR-2: Claude CLI requires ANTHROPIC_API_KEY env var (T1-03-AR)
- **Severity**: HIGH
- **Justification**: Claude CLI has no file-based or stdin-based authentication mechanism. The env var exists only in the short-lived Celery worker subprocess.
- **Controls**: Subprocess lifetime is bounded by task timeout (1800s); runtime cleanup on task completion.

### AR-3: FERNET_KEY exposed on compromised server (T-AR-01)
- **Severity**: HIGH
- **Justification**: Infrastructure-level compromise is outside application-layer mitigation scope.
- **Controls**: Env var injection only (never in source code); `docker-compose.yml` `:?required` syntax enforces presence.

### AR-4: Temporary plaintext API key file on disk (T-AR-02)
- **Severity**: MEDIUM
- **Justification**: Significantly reduced attack surface compared to env var exposure. Root-level access required to read `0o600` files owned by the process user.
- **Controls**: `0o600` permissions; `shutil.rmtree()` cleanup on task completion; `/tmp` cleared on container restart.

## Audit Trail

| Timestamp | Action | Details |
|-----------|--------|---------|
| 2026-04-23 | Audit initiated | Security auditor verified all 18 threats from Plans 01-01, 01-02, 01-03 |
| 2026-04-23 | Code verification | Read and verified mitigations in: `backend/core/encryption.py`, `backend/core/config.py`, `backend/api/v2/providers.py`, `backend/alembic/versions/20260423_0001_encrypt_api_keys.py`, `backend/core/redis_lock.py`, `backend/tasks/develop_code.py`, `backend/services/task_service.py`, `docker-compose.yml`, `.env.example` |
| 2026-04-23 | Audit completed | 14 threats CLOSED (mitigations verified in code), 4 threats ACCEPTED (documented with justification), 0 threats OPEN |
