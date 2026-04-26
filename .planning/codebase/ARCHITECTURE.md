# Architecture

**Analysis Date:** 2026-04-20

## Pattern Overview

**Overall:** Docker-orchestrated, API-first site builder with a Vue SPA, a FastAPI control plane, generated per-site runtime repositories, and Celery-backed background execution.

**Key Characteristics:**
- The browser talks to a single edge application through `/api/`, `/api/v2/`, `/ws/`, `/preview/`, and `/sites/` paths exposed by `frontend/nginx.conf` and `docker-compose.yml`.
- Backend behavior is split between route modules in `backend/api/`, business logic in `backend/services/`, persistence models in `backend/models/`, and asynchronous work in `backend/tasks/`.
- Each user site is materialized as a git-backed working tree under `generated_sites/`, with preview processes started and stopped by `backend/services/site_service.py`.
- Long-running work is delegated to Celery workers declared in `backend/core/celery_app.py`, while task logs are streamed through Redis pub/sub and WebSockets via `backend/services/websocket_service.py`.
- External agent and CLI integrations are isolated behind a dedicated MCP bridge in `codex_mcp/app/server.py` and containerized runtime services in `docker-compose.yml`.

## Layers

**Delivery / UI Layer:**
- Purpose: Render the application shell, route users, and issue API calls.
- Location: `frontend/src/`, `frontend/index.html`, `frontend/nginx.conf`
- Contains: Vue 3 app bootstrap, router, Pinia stores, API clients, layout shell, and feature views.
- Depends on: `frontend/src/api/client.ts`, `frontend/src/router/index.ts`, `frontend/src/stores/*`, and the backend API surface.
- Used by: End users and browser automation in `frontend/playwright.config.ts`.

**Edge / HTTP Layer:**
- Purpose: Terminate requests, enforce auth, and expose versioned APIs plus legacy compatibility routes.
- Location: `backend/main.py`, `backend/api/__init__.py`, `backend/api/v1/`, `backend/api/v2/`
- Contains: FastAPI app setup, CORS, startup/shutdown hooks, route registration, health endpoints, preview proxying, and websocket routes.
- Depends on: `backend/api/deps.py`, `backend/core/security.py`, `backend/core/database.py`, and service singletons.
- Used by: `frontend/src/api/*.ts`, WebSocket clients, and container health checks.

**Domain / Service Layer:**
- Purpose: Encapsulate application behavior and keep route handlers thin.
- Location: `backend/services/`
- Contains: Site lifecycle, task lifecycle, auth, deploy, template, version, websocket, container, and multi-agent coordination.
- Depends on: SQLAlchemy models from `backend/models/`, filesystem paths, Redis, Celery, and subprocess execution.
- Used by: HTTP routes in `backend/api/` and Celery tasks in `backend/tasks/`.

**Data Model Layer:**
- Purpose: Define persisted entities and schema migration history.
- Location: `backend/models/`, `backend/alembic/`
- Contains: SQLAlchemy declarative models, mixins, enums, and Alembic revisions.
- Depends on: `backend/models/base.py` conventions and the configured database URL in `backend/core/config.py`.
- Used by: Services, migrations, bootstrap code in `backend/main.py`, and tests in `backend/tests/`.

**Async Execution Layer:**
- Purpose: Run long-lived or blocking work outside the request cycle.
- Location: `backend/core/celery_app.py`, `backend/tasks/`
- Contains: Celery app definition, task routing, CLI execution wrappers, deployment jobs, and Playwright smoke testing.
- Depends on: Redis broker/result backend, `backend/services/task_service.py`, `backend/services/site_service.py`, and container runtime tools.
- Used by: Task creation flows in `backend/services/task_service.py` and deploy flows in `backend/services/deploy_service.py`.

**Generated Site Runtime Layer:**
- Purpose: Host per-site source trees that can be edited, previewed, cloned, and restarted independently.
- Location: `generated_sites/` at runtime, scaffolded by `backend/services/site_service.py`
- Contains: Per-site `backend/`, `frontend/`, and `docs/` subtrees plus git metadata.
- Depends on: Local git availability, site-specific process management, and the active site port range.
- Used by: Preview proxying in `backend/main.py`, file browser endpoints in `backend/api/v2/sites.py`, and worker tasks that mutate a site.

**Integration / Observability Layer:**
- Purpose: Connect external tools and expose operational signals.
- Location: `codex_mcp/app/server.py`, `monitoring/`, `docker-compose.yml`
- Contains: Codex MCP bridge, Prometheus scrape config, Grafana dashboards, and container topology.
- Depends on: Codex CLI, Redis, Prometheus, Grafana, MinIO, PostgreSQL, and Docker socket access for build/deploy workflows.
- Used by: Provider auth flows in `backend/main.py`, task execution in `backend/services/task_service.py`, and operators watching metrics.

## Data Flow

**Request to UI Flow:**
1. The browser loads the Vue SPA from `frontend/nginx.conf` and `frontend/Dockerfile`.
2. `frontend/src/main.ts` mounts the app, router, and Pinia stores; `frontend/src/api/client.ts` injects the access token into outgoing requests.
3. Requests land in `backend/main.py` through the Nginx reverse proxy and are routed to `backend/api/v2/*` or legacy `/api/*` handlers.
4. Route handlers delegate to service singletons such as `site_service`, `task_service`, `auth_service`, and `deploy_service`.
5. Services persist state through SQLAlchemy sessions from `backend/core/database.py`, mutate files under `generated_sites/`, and enqueue background work when needed.

**Authentication Flow:**
1. Credentials are submitted through `backend/api/v2/auth.py`.
2. `backend/services/auth_service.py` hashes passwords, creates JWT access and refresh tokens, and serializes the current user.
3. `backend/core/security.py` validates bearer tokens for protected routes through `OAuth2PasswordBearer` and `get_current_user`.
4. The frontend stores the tokens in localStorage through `frontend/src/stores/auth.ts` and reuses them via the axios interceptor in `frontend/src/api/client.ts`.

**Task Flow:**
1. The UI submits a task payload to `backend/api/v2/tasks.py` or the legacy handlers in `backend/main.py`.
2. `backend/services/task_service.py` creates an `AgentTask`, writes an initial `AgentTaskLog`, and routes the task to Celery via `backend/core/celery_app.py`.
3. Celery workers in `backend/tasks/develop_code.py`, `backend/tasks/deploy.py`, and `backend/tasks/test.py` run the job and call back into the task service.
4. Each log append publishes a Redis message through `backend/services/websocket_service.py`.
5. Connected clients receive incremental updates through `/ws/tasks/{task_id}/logs` and the UI log viewers.

**Site Runtime Flow:**
1. Site creation calls `backend/services/site_service.py`, which assigns a port, materializes the site root, and initializes a git repo when needed.
2. Starting a site launches a subprocess inside the generated site root with the port passed in the environment.
3. Preview requests to `/preview/{site_id}` and `/sites/{site_id}` in `backend/main.py` proxy directly to the site’s internal URL.
4. Adjustments update `generated_sites/<site_id>/backend/site_data.json`, then restart the preview process.
5. Deleting a site stops the process, soft-deletes the database row when supported, and removes the generated site tree.

**State Management:**
- The database is the source of truth for users, organizations, sites, tasks, templates, versions, and provider configuration.
- Running site processes and provider-auth subprocesses are held in memory inside `backend/services/site_service.py` and `backend/main.py`.
- Redis is the event bus for task logs and the broker/result backend for Celery.
- The filesystem under `generated_sites/` stores generated code, site docs, and per-site metadata.

## Key Abstractions

**Site:**
- Purpose: Represent a user-managed runtime site with its own port, preview URL, and generated source tree.
- Examples: `backend/models/site.py`, `backend/services/site_service.py`, `backend/api/v2/sites.py`
- Pattern: Site metadata lives in the database, while the source tree lives on disk at `generated_sites/<site_id>/`.

**Task / TaskLog:**
- Purpose: Represent queued work and its streaming output.
- Examples: `backend/models/task.py`, `backend/services/task_service.py`, `backend/api/v2/tasks.py`
- Pattern: The task row captures status transitions; the log table captures ordered output lines and is mirrored to WebSocket clients.

**UserLLMProvider:**
- Purpose: Store per-user CLI/LLM configuration used for Codex and Claude execution modes.
- Examples: `backend/models/user_llm_provider.py`, `backend/api/v2/providers.py`, `backend/services/task_service.py`
- Pattern: The provider record is queried at task start and converted into environment variables or command-line arguments.

**SiteDeployConfig / SiteProviderConfig:**
- Purpose: Keep per-site deployment and provider command settings isolated from core site metadata.
- Examples: `backend/models/site.py`, `backend/main.py`
- Pattern: The config objects are loaded with defaults, patched from incoming payloads, and stored as separate tables keyed by `site_id`.

**Service Singletons:**
- Purpose: Provide a single importable facade for orchestration logic.
- Examples: `backend/services/site_service.py`, `backend/services/task_service.py`, `backend/services/auth_service.py`, `backend/services/deploy_service.py`
- Pattern: Route handlers import the singleton instance and call methods directly instead of constructing per-request service objects.

## Entry Points

**FastAPI backend:**
- Location: `backend/main.py`
- Triggers: `main_service/Dockerfile`, `backend/main.py`, and `backend/__main__` style startup through uvicorn.
- Responsibilities: App bootstrap, router registration, CORS, startup data seeding, background subscriber startup, health checks, preview proxying, and legacy compatibility endpoints.

**API router assembly:**
- Location: `backend/api/__init__.py`
- Triggers: Imported by `backend/main.py`.
- Responsibilities: Combine v1 and v2 routers into a single `api_router`.

**Frontend bootstrap:**
- Location: `frontend/src/main.ts`
- Triggers: Vite dev server and production build.
- Responsibilities: Mount Pinia, router, lazy-loading plugin, virtual scroller, and global styles.

**Main service runtime:**
- Location: `main_service/app/main.py`
- Triggers: `main_service/Dockerfile` container start.
- Responsibilities: Start the same backend app for production execution in the runtime image.

**Codex MCP bridge:**
- Location: `codex_mcp/app/server.py`
- Triggers: `codex_mcp/Dockerfile` container start.
- Responsibilities: Start `codex mcp-server`, expose OAuth helpers, and report MCP/auth status.

**Container topology:**
- Location: `docker-compose.yml`
- Triggers: Local and CI-style orchestration.
- Responsibilities: Connect PostgreSQL, Redis, MinIO, main service, Celery, Flower, monitoring, frontend, and the MCP bridge.

## Error Handling

**Strategy:** HTTP-facing code prefers explicit `HTTPException` and JSON responses with `ok` plus a human-readable `message`; async jobs record failures in task state and logs rather than raising back into the UI.

**Patterns:**
- `backend/services/site_service.py` validates site IDs, file paths, and process state before touching the filesystem or launching subprocesses.
- `backend/services/task_service.py` marks task lifecycle transitions with timestamps and emits status updates to websocket subscribers.
- `backend/main.py` returns proxy failures as 502 JSON payloads and returns 409 when a preview target is not running.
- `backend/api/v2/providers.py` and `backend/main.py` validate provider names against `settings.provider_list` before starting auth flows.
- `backend/core/security.py` and `backend/api/deps.py` centralize authentication and produce consistent 401/403 responses.

## Cross-Cutting Concerns

**Logging:** Request logs come from Uvicorn; task and provider flows append structured lines to the database and publish them to WebSocket clients through `backend/services/websocket_service.py` and `backend/main.py`.

**Validation:** Input validation is split between FastAPI request parsing, `pydantic_settings` in `backend/core/config.py`, helper validation in `backend/utils/validation.py`, and SQLAlchemy constraints in `backend/models/`.

**Authentication:** Access control is bearer-token based through `backend/core/security.py`; the frontend keeps tokens in localStorage via `frontend/src/stores/auth.ts` and enforces route guards in `frontend/src/router/index.ts`.

**Metrics / Health:** `backend/core/metrics.py` exposes Prometheus instrumentation, while `/health` and `/api/health` in `backend/main.py` probe database, Redis, and MinIO readiness.

---

*Architecture analysis: 2026-04-20*