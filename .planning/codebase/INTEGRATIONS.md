# External Integrations

**Analysis Date:** 2026-04-20

## APIs & External Services

**Database:**
- PostgreSQL - Primary application database for the backend in `docker-compose.yml`, `backend/core/database.py`, and `backend/models/`
  - Connection: `DATABASE_URL` / `SYNC_DATABASE_URL`
  - Client: SQLAlchemy async engine with `asyncpg` for async access and `psycopg[binary]` for sync access in `backend/core/config.py`
- SQLite - Local/test fallback used when PostgreSQL is unavailable
  - Connection: `sqlite+aiosqlite` in `docker-compose.yml` test service and `backend/core/database.py`
  - Client: SQLAlchemy async engine with `aiosqlite`

**Object Storage:**
- MinIO - Used for site version snapshots and template archives in `backend/utils/minio.py`, `backend/services/version_service.py`, and `backend/services/template_service.py`
  - SDK/Client: `minio`
  - Auth: `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`
  - Endpoint: `MINIO_ENDPOINT`
  - Buckets: `site-templates`, `site-versions`

**Message Queue / Cache:**
- Redis - Celery broker/result backend and task log pub/sub in `docker-compose.yml`, `backend/core/celery_app.py`, and `backend/services/websocket_service.py`
  - Auth: `REDIS_PASSWORD`
  - Client: `redis` / `redis.asyncio`

**Task Processing:**
- Celery - Asynchronous execution for development, deploy, and test tasks in `backend/tasks/`
  - Worker entry point: `backend/core/celery_app.py`
  - Queues: `ai-tasks`, `deploy-tasks`, `test-tasks`
  - Monitoring: `flower` service in `docker-compose.yml`

**Code / Site Management:**
- Git repositories - Generated sites can be cloned, initialized, committed, and rolled back in `backend/services/site_service.py` and `backend/services/version_service.py`
  - Integration style: local CLI invocation via `git`
  - Auth: optional HTTP(S) embedded credentials when `git_username` / `git_password` are supplied
- Docker Engine - Runtime container management for generated sites in `backend/services/container_service.py` and `backend/utils/docker.py`
  - Integration style: local `docker` CLI

**LLM / Agent Providers:**
- Local CLI providers - Codex, Claude Code, and Gemini CLI are invoked by backend task flows in `backend/core/config.py`, `backend/services/task_service.py`, and `docker-compose.yml`
  - CLIs: `codex`, `claude`, `gemini`
  - Auth commands: `CODEX_AUTH_CMD`, `CLAUDE_AUTH_CMD`, `GEMINI_AUTH_CMD`
- Custom LLM endpoints - User-defined provider records are managed in `backend/api/v2/providers.py` and stored via `backend/models/user_llm_provider.py`
  - SDK/Client: `httpx`
  - Default discovery call: `GET {base_url}/models`
  - Auth: bearer token supplied from the saved API key

**MCP Services:**
- Built-in MCP services - Managed in `backend/services/mcp_service.py`
  - Services: `context7`, `open-websearch`, `spec-workflow`, `deepwiki`, `playwright`, `exa`
  - Validation: required fields enforced per service in `backend/services/mcp_service.py`
- MCP bridge process - `CODEX_MCP_BRIDGE_URL` points to the bridge service defined in `docker-compose.yml`

**Browser Automation / E2E:**
- Playwright - Used for smoke tests and browser-based validation in `backend/tasks/test.py`, `main_service/app/scripts/playwright_smoke_runner.mjs`, and `frontend/playwright.config.ts`
  - Browser target: Chromium
  - Base URL: `PLAYWRIGHT_BASE_URL`

## Data Storage

**Databases:**
- PostgreSQL is the primary persistent store for users, sites, tasks, templates, versions, and org membership in `backend/models/`.
- SQLite is used for test isolation and local fallback paths in `backend/core/database.py` and the `test` service in `docker-compose.yml`.

**File Storage:**
- Local filesystem is used for generated site roots, task artifacts, and shared runtime data in `backend/core/config.py`, `backend/services/site_service.py`, and `backend/services/task_service.py`.
  - Shared root: `/shared`
  - Generated sites root: `/generated_sites`
  - Task artifacts: `/shared/task_artifacts` or `data/task_artifacts`
- MinIO stores serialized archives and snapshots for versions/templates in `backend/utils/minio.py` and `backend/services/version_service.py`.

**Caching:**
- No dedicated cache service detected beyond Redis usage for queueing and websocket pub/sub.

## Authentication & Identity

**Auth Provider:**
- Custom JWT authentication implemented in `backend/core/security.py` and exposed by `backend/api/v2/auth.py`.
  - Login endpoint: `/api/v2/auth/login`
  - Refresh endpoint: `/api/v2/auth/refresh`
  - Token type: bearer JWT
  - Password hashing: `passlib[bcrypt]` with `pbkdf2_sha256`
- Organization membership and role checks are enforced in `backend/api/deps.py`.
- Default bootstrap admin and organization are created in `backend/main.py` during startup.

## Monitoring & Observability

**Error Tracking:**
- No external error-tracking service detected.

**Metrics:**
- Prometheus instrumentation in `backend/core/metrics.py`
  - Scrape endpoint: `/metrics`
  - Scrape target: `main-service:8080`
- Grafana dashboards and provisioning are mounted through `docker-compose.yml` and `monitoring/grafana/provisioning/`.
- Flower provides Celery task visibility on port 20101 via `docker-compose.yml`.

**Logs:**
- Application logs are emitted through standard Python logging in `backend/main.py` and related service modules.
- Real-time task logs are published through Redis pub/sub in `backend/services/websocket_service.py` and delivered over `/ws/tasks/{task_id}/logs` in `backend/api/v2/websocket.py`.

## CI/CD & Deployment

**Hosting:**
- Docker Compose is the deployment unit for the entire stack in `docker-compose.yml`.
- The frontend is served by Nginx in `frontend/Dockerfile` and reverse-proxied to backend services in `frontend/nginx.conf`.

**CI Pipeline:**
- No CI provider or pipeline configuration detected in the repository files reviewed.

## Environment Configuration

**Required env vars:**
- `SECRET_KEY` is required by `backend/core/config.py` and enforced at startup.
- Database, Redis, MinIO, and CORS values are configured via `docker-compose.yml` and `backend/core/config.py`.
- Provider command and auth variables are configured in `docker-compose.yml` for `CODEX_CMD`, `CLAUDE_CMD`, `GEMINI_CMD`, and related auth commands.
- `PLAYWRIGHT_BASE_URL` controls browser smoke tests in `main_service/app/scripts/playwright_smoke_runner.mjs` and `backend/tasks/test.py`.

**Secrets location:**
- Environment values are loaded from `.env` by `backend/core/config.py`.
- `start.sh` requires `.env` to exist before bringing up the stack.
- Secret values are passed as environment variables in `docker-compose.yml`; no secret manager integration was detected.

## Webhooks & Callbacks

**Incoming:**
- WebSocket log stream for tasks: `/ws/tasks/{task_id}/logs` in `backend/api/v2/websocket.py`
- No HTTP webhook receiver was detected.

**Outgoing:**
- Model/provider discovery requests to user-supplied LLM endpoints in `backend/api/v2/providers.py` (`GET /models`).
- Skill imports from `skills.sh` pages in `backend/services/skill_service.py` via `httpx`.
- Template archive and version snapshot uploads/downloads through MinIO in `backend/utils/minio.py`.
- Celery task log events are published over Redis pub/sub from `backend/services/websocket_service.py` rather than through webhooks.

---

*Integration audit: 2026-04-20*