# Technology Stack

**Analysis Date:** 2026-04-20

## Languages

**Primary:**
- Python 3.12 - Backend API, worker tasks, service layer, CLI helpers in `backend/`, `main_service/`, `codex_mcp/`, and `scripts/`
- TypeScript 5.9 - Frontend application code in `frontend/src/`

**Secondary:**
- Bash - Local orchestration script in `start.sh`
- SQL - Database migrations and schema definitions in `backend/alembic/versions/`
- JavaScript / MJS - Playwright smoke runner in `main_service/app/scripts/playwright_smoke_runner.mjs`

## Runtime

**Environment:**
- Python 3.12 slim images for the backend runtime in `main_service/Dockerfile`
- Node.js 20 Alpine for the frontend build stage in `frontend/Dockerfile`
- Docker Compose stack for local and production-style orchestration in `docker-compose.yml`

**Package Manager:**
- `pip` for Python dependencies in `main_service/requirements.txt` and `main_service/requirements-dev.txt`
- `npm` for frontend dependencies in `frontend/package.json`
- `npm` for runtime tooling in `main_service/package.json`
- Lockfiles present: `frontend/package-lock.json`, `main_service/package-lock.json`

## Frameworks

**Core:**
- FastAPI 0.116.1 - HTTP API and WebSocket backend in `backend/main.py` and `backend/api/v2/`
- SQLAlchemy 2.0.43 - Async ORM and session handling in `backend/core/database.py` and `backend/models/`
- Alembic 1.16.5 - Database migrations in `backend/alembic/`
- Celery 5.5.3 with Redis - Background task execution in `backend/core/celery_app.py` and `backend/tasks/`
- Pydantic 2.11.7 / pydantic-settings 2.10.1 - Settings and schema validation in `backend/core/config.py` and `backend/schemas/`
- Vue 3.5.30 - Frontend application framework in `frontend/src/`
- Vue Router 5.0.4 - Routing in `frontend/src/router/index.ts`
- Pinia 3.0.4 - Client state management in `frontend/src/stores/`

**Testing:**
- pytest 8.0.0 - Python test runner configured in `pytest.ini`
- pytest-asyncio 0.23.5 - Async test support in `backend/tests/`
- pytest-cov 4.1.0 - Coverage reporting in `docker-compose.yml` and `pytest.ini`
- Playwright 1.58.2 - End-to-end/browser automation in `frontend/playwright.config.ts` and `main_service/app/scripts/playwright_smoke_runner.mjs`
- Vitest 4.1.0 - Frontend unit testing dependency in `frontend/package.json`

**Build/Dev:**
- Vite 8.0.1 - Frontend build/dev server in `frontend/vite.config.ts`
- Uvicorn 0.35.0 - ASGI server in `main_service/Dockerfile`
- Nginx - Static frontend serving and reverse proxy in `frontend/Dockerfile` and `frontend/nginx.conf`
- Flower 2.0.1 - Celery monitoring in `docker-compose.yml`
- Prometheus client 0.22.1 - Metrics instrumentation in `backend/core/metrics.py`

## Key Dependencies

**Critical:**
- `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `alembic` - API runtime, persistence, and schema evolution in `backend/`
- `celery[redis]`, `redis` - Queue processing and websocket log fanout in `backend/core/celery_app.py` and `backend/services/websocket_service.py`
- `minio` - Snapshot and template object storage in `backend/utils/minio.py` and `backend/services/version_service.py`
- `python-jose[cryptography]`, `passlib[bcrypt]` - JWT auth and password hashing in `backend/core/security.py`
- `httpx` - Outbound HTTP calls in `backend/api/v2/providers.py` and `backend/services/skill_service.py`

**Frontend UI stack:**
- `axios` - API client in `frontend/src/api/client.ts`
- `vee-validate`, `@vee-validate/zod`, `zod` - Form validation in `frontend/src/`
- `monaco-editor` - Code editing experience in `frontend/src/components/Editor/CodeEditor.vue`
- `echarts`, `vue-echarts` - Charts and dashboards in `frontend/src/views/`
- `lucide-vue-next`, `radix-vue`, `reka-ui`, `vue-sonner`, `vue-virtual-scroller` - UI primitives and interaction helpers in `frontend/src/components/`

**Infrastructure / tooling:**
- `@vitejs/plugin-vue`, `unplugin-auto-import`, `unplugin-vue-components` - Frontend compile-time tooling in `frontend/vite.config.ts`
- `playwright` - Browser automation in `main_service/package.json` and `frontend/package.json`
- `@openai/codex` - CLI agent runtime installed in `main_service/Dockerfile`
- `git`, `docker.io`, `ripgrep`, `jq`, `nodejs`, `npm` - Runtime tooling required by `main_service/Dockerfile` for generated-site workflows

## Configuration

**Environment:**
- Settings are loaded from `.env` and environment variables through `backend/core/config.py`.
- Compose overrides are declared in `docker-compose.yml` for database, Redis, MinIO, Celery, CORS, provider commands, and site runtime ports.
- Frontend API target is controlled by `VITE_API_BASE_URL` in `frontend/src/api/client.ts` and proxied during dev from `frontend/vite.config.ts`.
- Test execution is pinned by `pytest.ini` and the `test` service in `docker-compose.yml`.

**Build:**
- `frontend/Dockerfile` builds the Vue app in a Node stage and serves it through Nginx.
- `main_service/Dockerfile` builds the backend image, installs Python deps, Playwright Chromium, and global Codex tooling, then launches `uvicorn backend.main:app`.
- `codex_mcp/Dockerfile` builds the MCP bridge service used by the main backend.
- `backend/alembic.ini` and `backend/alembic/env.py` define migration behavior.

## Platform Requirements

**Development:**
- Docker Engine and Docker Compose are required for the full stack in `start.sh`.
- Python 3.12 and Node 20+ are the effective base versions used by the container images.
- Browser automation requires Playwright Chromium, installed in `main_service/Dockerfile` and used by `frontend/playwright.config.ts`.
- Git is required in the runtime image because generated sites are initialized as repositories in `backend/services/site_service.py`.

**Production:**
- The repository is deployed as a multi-container Compose application with `frontend`, `main-service`, `celery-worker`, `celery-beat`, `flower`, `prometheus`, `grafana`, `redis`, `postgres`, `minio`, and `codex-mcp` defined in `docker-compose.yml`.
- Public entry points are exposed on ports 20100, 20101, 20102, and 20103 as defined in `docker-compose.yml` and documented by `start.sh`.

---

*Stack analysis: 2026-04-20*