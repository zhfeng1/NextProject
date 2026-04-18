# Security Hardening Review Fix Report

**Phase:** 01-security-hardening
**Date:** 2026-04-23
**Iteration:** 1

---

## Fixes Applied

### C1 — `fetch-models` SSRF + API Key leak (CRITICAL)

**Status:** FIXED
**Commit:** `5623910` — fix(01): add SSRF protection to fetch-models and verify-model endpoints
**File:** `backend/api/v2/providers.py`
**Changes:**
- Added `_validate_url_ssrf()` helper that resolves hostname via DNS then checks all resolved IPs against a blocklist of private/internal networks (RFC1918, loopback, link-local, IPv6 ULA/link-local, `0.0.0.0/8`)
- Applied SSRF validation to `fetch-models` endpoint
- `fetch-models` now accepts `provider_id` to retrieve the encrypted API key from DB, reducing the need to transmit plaintext keys
- Backward-compatible: `api_key` field still accepted as fallback when `provider_id` is not provided

### C2 — `verify-model` SSRF incomplete (CRITICAL)

**Status:** FIXED
**Commit:** `5623910` — fix(01): add SSRF protection to fetch-models and verify-model endpoints
**File:** `backend/api/v2/providers.py`
**Changes:**
- Replaced simple scheme check with full `_validate_url_ssrf()` call that performs DNS resolution + IP blocklist validation
- Shared implementation with C1 fix ensures consistent protection

### H1 — Docker Socket exposure (HIGH)

**Status:** SKIPPED — requires manual infrastructure change
**Reason:** Docker Socket (`/var/run/docker.sock`) is mounted by `docker-compose.yml` for `main-service` and `celery-worker`. Removing or restricting it requires evaluating which features depend on it (likely sub-site container management) and potentially introducing a Docker socket proxy (e.g., Tecnativa/docker-socket-proxy). This is an infrastructure-level change that must be planned and tested manually.

### H2 — Celery worker command injection (HIGH)

**Status:** FIXED
**Commit:** `23ec1c3` — fix(01): remove user-supplied command execution to prevent command injection
**File:** `backend/services/task_service.py`
**Changes:**
- `command` field is now stripped from `payload_data` in `create_task()` before persisting to DB
- `_run_develop_task_for_provider()` no longer reads `command` from payload (hardcoded to empty string)
- Provider commands are now exclusively derived from server-side configuration (env vars and DB provider records)

### H3 — Default admin credentials hardcoded (HIGH)

**Status:** FIXED
**Commit:** `037b080` — fix(01): warn on default admin credentials and enforce minimum password length
**File:** `backend/core/config.py`
**Changes:**
- `default_admin_email` and `default_admin_password` are now configurable via `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` environment variables
- Added `validate_default_admin_password` field validator that:
  - Emits a warning when well-known insecure defaults are detected (`admin123456`, `admin`, `password`, `123456`)
  - Rejects passwords shorter than 8 characters
- Production deployments should set `DEFAULT_ADMIN_PASSWORD` to a strong value

### H4 — API Key via env vars to subprocesses (HIGH)

**Status:** ACCEPTED RISK (no code change needed)
**Reason:** The Claude CLI only supports `ANTHROPIC_API_KEY` via environment variable — no file-based alternative exists. Existing mitigations are adequate:
1. Environment variables are scoped to the short-lived subprocess and destroyed on process exit
2. API key files (`/tmp/nextproject-task-runtime/<task_id>/api_key`) are created with `0600` permissions and cleaned up by `_cleanup_task_runtime()` on task completion (SUCCESS/FAILED/CANCELED)
3. The `codex` provider uses file-based key injection via `CODEX_TASK_API_KEY_FILE` (already secure)

**Recommendation for future:** Consider mounting `/proc` with `hidepid=2` in worker containers to prevent cross-process `/proc/<pid>/environ` reading.

---

## Summary

| Finding | Severity | Status | Commit |
|---------|----------|--------|--------|
| C1 | CRITICAL | FIXED | `5623910` |
| C2 | CRITICAL | FIXED | `5623910` |
| H1 | HIGH | SKIPPED (infra) | — |
| H2 | HIGH | FIXED | `23ec1c3` |
| H3 | HIGH | FIXED | `037b080` |
| H4 | HIGH | ACCEPTED RISK | — |
