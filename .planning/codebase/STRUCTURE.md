# Codebase Structure

**Analysis Date:** 2026-04-20

## Directory Layout

```text
NextProject/
├── backend/            # FastAPI backend, SQLAlchemy models, Celery tasks, Alembic migrations, tests
├── frontend/           # Vue 3 + Vite SPA, router, stores, UI components, API clients
├── main_service/       # Runtime image and helper scripts for the main backend service
├── codex_mcp/          # Codex MCP bridge service container and app
├── monitoring/         # Prometheus and Grafana provisioning
├── scripts/            # Bootstrap, migration, and maintenance scripts
├── k8s/                # Kubernetes manifests and overlays
├── docs/               # Project-facing documentation
├── data/               # Runtime persistent volume mounted by Docker Compose
├── generated_sites/    # Per-site runtime repositories created by the backend
├── docker-compose.yml  # Local multi-service orchestration
├── start.sh            # Local startup script referenced by project docs
├── pytest.ini          # Backend test configuration
└── .env.example        # Environment template consumed by `backend/core/config.py`
```

## Directory Purposes

**`backend/`:**
- Purpose: Main application backend and domain orchestration layer.
- Contains: API routers, dependency helpers, core settings, database wiring, security helpers, ORM models, Pydantic schemas, services, Celery tasks, Alembic migrations, utilities, and backend tests.
- Key files: `backend/main.py`, `backend/api/__init__.py`, `backend/core/config.py`, `backend/core/database.py`, `backend/services/site_service.py`, `backend/services/task_service.py`, `backend/tasks/develop_code.py`, `backend/tests/conftest.py`

**`frontend/`:**
- Purpose: Browser SPA and design-system component library.
- Contains: Vue entrypoints, router, Pinia stores, API clients, pages, shared UI components, assets, Tailwind/Vite config, Playwright config, and production Dockerfile/Nginx config.
- Key files: `frontend/src/main.ts`, `frontend/src/router/index.ts`, `frontend/src/api/client.ts`, `frontend/src/views/`, `frontend/src/components/Layout/AppLayout.vue`, `frontend/vite.config.ts`, `frontend/nginx.conf`

**`main_service/`:**
- Purpose: Build context for the production control-plane image that runs the backend and helper scripts.
- Contains: Dockerfile, runtime package manifest, Playwright smoke runner, and Node helper dependencies.
- Key files: `main_service/Dockerfile`, `main_service/app/main.py`, `main_service/app/scripts/playwright_smoke_runner.mjs`, `main_service/package.json`

**`codex_mcp/`:**
- Purpose: Independent bridge service that starts `codex mcp-server` and exposes OAuth/status endpoints.
- Contains: Dockerfile, Python app server, and requirements file.
- Key files: `codex_mcp/Dockerfile`, `codex_mcp/app/server.py`

**`monitoring/`:**
- Purpose: Observability provisioning for containerized monitoring.
- Contains: Prometheus scrape config and Grafana datasource/dashboard provisioning.
- Key files: `monitoring/prometheus.yml`, `monitoring/grafana/provisioning/datasources/prometheus.yml`, `monitoring/grafana/provisioning/dashboards/dashboard.yml`, `monitoring/grafana/provisioning/dashboards/nextproject-overview.json`

**`scripts/`:**
- Purpose: One-off bootstrap and migration helpers used by containers and local maintenance workflows.
- Contains: SQL initialization, agent bootstrap, template seeding, and migration validation scripts.
- Key files: `scripts/init.sql`, `scripts/init_agents.py`, `scripts/init_default_templates.py`, `scripts/migrate_sqlite_to_postgres.py`, `scripts/validate_migration.py`

**`k8s/`:**
- Purpose: Kubernetes deployment manifests for the backend stack.
- Contains: Base resources and dev/prod overlays.
- Key files: `k8s/base/deployment.yaml`, `k8s/base/service.yaml`, `k8s/base/worker-deployment.yaml`, `k8s/base/configmap.yaml`, `k8s/base/kustomization.yaml`, `k8s/overlays/dev/kustomization.yaml`, `k8s/overlays/prod/kustomization.yaml`

**`docs/`:**
- Purpose: Human-authored product and implementation notes.
- Contains: Planning notes, change summaries, and documentation drafts.
- Key files: `docs/README.md`, `docs/2.0.0-fix修复清单.md`, `docs/前端修改计划-v2.0.md`, `docs/文档更新总结.md`

**`data/`:**
- Purpose: Persistent runtime storage mounted into containers.
- Contains: SQLite/PostgreSQL-related files, artifacts, Codex home data, MinIO-related local state, and task artifacts depending on deployment mode.
- Key files: Not committed as source code; referenced by `docker-compose.yml` and `backend/core/config.py`.

**`generated_sites/`:**
- Purpose: Per-site git repositories created and managed at runtime.
- Contains: Site-specific `backend/`, `frontend/`, and `docs/` directories, plus `.git` metadata.
- Key files: `generated_sites/<site_id>/backend/app.py`, `generated_sites/<site_id>/backend/site_data.json`, `generated_sites/<site_id>/frontend/index.html`, `generated_sites/<site_id>/docs/requirements.md`

## Key File Locations

**Entry Points:**
- `backend/main.py`: FastAPI app bootstrap, router registration, startup/shutdown hooks, preview proxying, health checks, and legacy `/api/*` compatibility.
- `backend/api/__init__.py`: Router composition for v1 and v2 endpoints.
- `frontend/src/main.ts`: Vue application bootstrap.
- `frontend/src/App.vue`: Root router outlet.
- `main_service/app/main.py`: Container entrypoint that launches `backend.main:app`.
- `codex_mcp/app/server.py`: MCP bridge entrypoint.
- `docker-compose.yml`: Local multi-container runtime definition.

**Configuration:**
- `backend/core/config.py`: Shared settings, environment variables, and validation rules.
- `backend/alembic.ini`: Alembic migration configuration.
- `frontend/vite.config.ts`: Vite dev server, alias, and proxy setup.
- `frontend/tailwind.config.ts`: Tailwind theme and content scanning.
- `frontend/playwright.config.ts`: Browser test runner configuration.
- `frontend/nginx.conf`: Production reverse proxy and SPA fallback rules.
- `main_service/Dockerfile`: Main backend runtime image.
- `codex_mcp/Dockerfile`: MCP bridge image.
- `pytest.ini`: Test runner defaults for backend test execution.

**Core Logic:**
- `backend/services/site_service.py`: Site filesystem layout, process lifecycle, preview URL generation, file browser, cloning, and site restart logic.
- `backend/services/task_service.py`: Task creation, status transitions, command execution, and log streaming.
- `backend/services/auth_service.py`: Registration, login, refresh token handling, and user configuration.
- `backend/services/deploy_service.py`: Deployment task creation.
- `backend/services/websocket_service.py`: Redis-backed websocket broadcast manager.
- `backend/tasks/develop_code.py`, `backend/tasks/deploy.py`, `backend/tasks/test.py`: Celery task wrappers around service methods.
- `backend/models/site.py`, `backend/models/task.py`, `backend/models/user_llm_provider.py`: Core persisted entities used by the services.

**API Surface:**
- `backend/api/v2/auth.py`: Authentication and user profile endpoints.
- `backend/api/v2/sites.py`: Site CRUD, file browsing, and requirements endpoints.
- `backend/api/v2/tasks.py`: Task lifecycle endpoints.
- `backend/api/v2/deploy.py`: Deployment endpoint.
- `backend/api/v2/providers.py`: Per-user LLM provider configuration and remote model discovery.
- `backend/api/v2/templates.py`: Template listing and template-driven site creation.
- `backend/api/v2/versions.py`: Snapshot and rollback endpoints.
- `backend/api/v2/websocket.py`: Task log websocket stream.
- `backend/api/v1/sites.py`, `backend/api/v1/tasks.py`: Legacy route surface retained for compatibility.

**Testing:**
- `backend/tests/conftest.py`: Shared backend fixtures.
- `backend/tests/test_auth.py`, `backend/tests/test_cors.py`, `backend/tests/test_minio.py`, `backend/tests/test_sites.py`: Backend integration coverage.
- `frontend/playwright.config.ts`: E2E runner; tests are expected under `frontend/tests/e2e/`.
- `frontend/playwright-report/`: Generated Playwright output, not a source-of-truth directory for hand-written tests.

## Naming Conventions

**Files:**
- API routes use lowercase resource names under `backend/api/v2/`: `sites.py`, `tasks.py`, `templates.py`, `versions.py`, `providers.py`.
- Service modules use the `<name>_service.py` pattern: `backend/services/site_service.py`, `backend/services/task_service.py`.
- Celery tasks use action-oriented module names: `backend/tasks/develop_code.py`, `backend/tasks/deploy.py`, `backend/tasks/test.py`.
- Vue components use PascalCase file names: `frontend/src/components/Layout/AppLayout.vue`, `frontend/src/views/Sites/SiteEditor.vue`.
- Shared UI primitives live in lower-case folders with PascalCase components: `frontend/src/components/ui/button/Button.vue`.
- Per-site docs use lowercase file names such as `generated_sites/<site_id>/docs/requirements.md`.

**Directories:**
- Python backend layers are grouped by concern: `api/`, `core/`, `models/`, `schemas/`, `services/`, `tasks/`, `tests/`, `utils/`.
- Frontend feature areas are grouped by domain: `views/Auth/`, `views/Sites/`, `views/Tasks/`, `views/Templates/`, `views/Settings/`.
- Shared UI primitives are grouped by component family: `components/ui/button/`, `components/ui/dialog/`, `components/ui/sidebar/`.

## Where to Add New Code

**New Backend Feature:**
- Primary route: `backend/api/v2/<feature>.py`
- Business logic: `backend/services/<feature>_service.py`
- Persistence: `backend/models/<feature>.py` and `backend/schemas/<feature>.py`
- Registration: `backend/api/__init__.py`
- Migration: `backend/alembic/versions/`

**New Frontend Page or Flow:**
- Route component: `frontend/src/views/<Area>/<Page>.vue`
- Route table: `frontend/src/router/index.ts`
- API client: `frontend/src/api/<feature>.ts`
- Shared state: `frontend/src/stores/<feature>.ts`
- Shared layout/UI: `frontend/src/components/Layout/` or `frontend/src/components/ui/`

**New Background Job:**
- Task wrapper: `backend/tasks/<job>.py`
- Celery routing: `backend/core/celery_app.py`
- Implementation: `backend/services/<domain>_service.py`
- Log emission and status updates: `backend/services/task_service.py`

**New Site Runtime Behavior:**
- Site filesystem and process control: `backend/services/site_service.py`
- Preview proxy behavior: `backend/main.py`
- Generated site docs/templates: `backend/services/site_service.py`
- Runtime storage: `generated_sites/` and `data/`

**New Monitoring or Ops Asset:**
- Prometheus config: `monitoring/prometheus.yml`
- Grafana provisioning: `monitoring/grafana/provisioning/`
- Container wiring: `docker-compose.yml`
- Kubernetes manifests: `k8s/`

## Special Directories

**`generated_sites/`:**
- Purpose: Runtime-generated repositories for each site.
- Generated: Yes.
- Committed: No for site contents; the directory is managed by the application at runtime.

**`data/`:**
- Purpose: Persistent application storage mounted into containers.
- Generated: Yes.
- Committed: No.

**`backend/alembic/`:**
- Purpose: Database schema migration history.
- Generated: Partially; revisions are committed source artifacts.
- Committed: Yes.

**`frontend/src/components/ui/`:**
- Purpose: Shared design-system primitives used across the SPA.
- Generated: No.
- Committed: Yes.

**`frontend/playwright-report/`:**
- Purpose: Browser test report output.
- Generated: Yes.
- Committed: No for day-to-day development.

---

*Structure analysis: 2026-04-20*