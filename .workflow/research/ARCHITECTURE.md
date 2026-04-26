# Architecture Research

## Current Architecture
- The codebase is a single deployable product with clear runtime planes but shared code: Vue 3 SPA behind Nginx, one FastAPI control plane (`main-service`), Celery workers/beat for async work, and shared PostgreSQL/Redis/MinIO infrastructure via Docker Compose.
- The backend is effectively a modular monolith, but it currently has two API surfaces: router-based `/api/v2/*` modules under `backend/api/v2/` and a still-large legacy `/api/*` surface implemented directly in `backend/main.py`.
- Main domain boundaries already exist in the data model: sites, tasks, workflows, conversations, templates, users/orgs. Operationally, there are also distinct planes: control/API, async execution, site preview runtime, and stateful services.
- Site preview is a special architectural boundary: managed sites are started as local processes by `site_service`, bound to per-site ports, then exposed through `/preview/{site_id}` and `/sites/{site_id}` reverse proxying. That makes the main API service also act as a lightweight runtime supervisor.
- Workflow and conversation features are emerging as orchestration layers on top of the core site/task model. They add useful product capability, but today they are coupled into the same service layer rather than isolated as first-class application modules.

## Data/Control Flow
1. User acts in the Vue UI; Axios targets `/api/v2`, while Nginx proxies `/api/` and `/ws/` to `main-service`.
2. FastAPI routers call service-layer methods, which persist site/task/workflow/conversation state in PostgreSQL and store runtime/config payloads in JSON columns.
3. Creating a task writes an `AgentTask` row, appends task logs, and enqueues work to Celery; Redis is the queue/broker boundary and also supports result/state exchange.
4. Celery workers run provider CLI commands, deploy tasks, or Playwright smoke tests; task status/logs are written back to PostgreSQL and published through Redis pub/sub so WebSocket clients can stream updates, with frontend polling as fallback.
5. Successful development tasks usually trigger a site preview restart, so the control flow loops back into runtime management before the updated site is visible through the preview proxy.
6. Some state also lives outside the database: generated site code under `generated_sites/`, workflow artifacts under `.np/workflows/`, provider output logs under shared task artifact directories, and provider auth process state in memory/files. This makes the system workable, but the control flow crosses DB, filesystem, Redis, and in-process memory.

## Main Structural Frictions
- `backend/main.py` is overloaded. It assembles the app, bootstraps data, exposes legacy APIs, manages provider auth flows, proxies site traffic, and owns health/metrics. FastAPI guidance for larger apps is the opposite: keep `main.py` as composition and push behavior into routers/dependencies.
- The dual API surface creates drag. Legacy `/api/*` and newer `/api/v2/*` both exist, which raises migration cost, weakens contract clarity, and makes auth/authorization behavior harder to reason about.
- `site_service` mixes too many responsibilities: database access, filesystem scaffolding, git clone/init, path validation, process supervision, preview metadata, and restart behavior. That is the system’s most obvious boundary violation.
- `task_service` is also carrying too much: task CRUD, workflow gating, provider command construction, shell execution, log persistence, WebSocket fan-out, provider output capture, and post-task site restarts. Adding more providers or task types will increase branching pressure quickly.
- Runtime truth is split across multiple stores. Example: site/task state is in PostgreSQL, artifacts are on disk, live site processes are tracked in `_SITE_PROCESSES`, and auth subprocesses are tracked in memory. This assumes a largely single-instance control plane and makes recovery/reconciliation harder.
- There is already evidence of file-contract drift: site requirements are written to `docs/requirements.md`, while conversation context assembly reads `docs/requirement.md`. That kind of mismatch is a symptom of weak internal contracts between modules.
- Naming and identity boundaries are not fully normalized (`site.id` vs `site.site_id`, `Task = AgentTask`, mixed public IDs vs DB IDs). The system is still understandable, but these inconsistencies increase accidental complexity across API, service, and UI layers.

## Recommended Near-Term Direction
- Keep this system as a modular monolith for now; do not split it into microservices yet. The current pain is mostly internal boundary quality, not lack of network boundaries. This aligns with brownfield "monolith first, extract later" guidance.
- Make `backend/main.py` a composition root over the near term: app creation, middleware, startup/shutdown, and `include_router(...)` only. Move remaining legacy endpoints into explicit router modules, even if some stay marked as legacy.
- Formalize four internal ownership areas without rewriting the product:
  - `sites`: site metadata, requirements, file browsing, template linkage.
  - `runtime`: preview process lifecycle, port allocation, proxy metadata, restart/reconciliation.
  - `tasks/execution`: task records, Celery dispatch, provider adapters, log/status streaming.
  - `workflow/conversation`: planning context, stage artifacts, multi-turn AI interactions.
- Extract adapters before extracting services. In practice, the next useful seams are a `SiteRuntimeManager` and provider-specific task runners. That reduces branching inside `site_service` and `task_service` while keeping deployment topology stable.
- Standardize state contracts: PostgreSQL should be the source of truth for business state, filesystem should hold artifacts only, and in-memory maps should be treated as caches that can be rebuilt. Also normalize naming around public IDs vs internal DB IDs and unify artifact file names.
- Preserve the current Docker Compose operational split: frontend delivery plane, API/control plane, worker plane, scheduler/monitoring plane, and stateful services plane. Celery already gives a meaningful async boundary; use it as the execution boundary instead of introducing new remote services prematurely.
- If one future extraction becomes necessary, the best candidate is the site runtime supervisor, because preview process lifecycle and port/process management have different scaling and failure characteristics from the HTTP control plane. But that should come after API consolidation and internal module cleanup, not before.
