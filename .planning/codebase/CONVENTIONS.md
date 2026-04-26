# Coding Conventions

**Analysis Date:** 2026-04-20

## Naming Patterns

**Files:**
- Python modules use `snake_case` and domain-based names, such as `backend/services/site_service.py`, `backend/api/v2/tasks.py`, and `backend/utils/validation.py`.
- Vue single-file components use `PascalCase` filenames, such as `frontend/src/views/Sites/SiteEditor.vue`, `frontend/src/components/Layout/AppLayout.vue`, and `frontend/src/components/TaskLogs.vue`.
- Test files use `test_*.py` in `backend/tests/` and `*.spec.ts` in `frontend/tests/e2e/`, for example `backend/tests/test_sites.py` and `frontend/tests/e2e/site-creation.spec.ts`.

**Functions:**
- Python functions and methods use `snake_case`, including FastAPI route handlers such as `create_site()` in `backend/api/v2/sites.py` and service methods such as `create_site()` and `start_site()` in `backend/services/site_service.py`.
- Vue components use `camelCase` for local functions and state helpers, such as `toggleSiteStatus()`, `loadSite()`, and `submitRequirement()` in `frontend/src/views/Sites/SiteList.vue` and `frontend/src/views/Sites/SiteEditor.vue`.
- Boolean predicates and guards are named to read as conditions, such as `is_process_running()` in `backend/services/site_service.py` and `isTerminal()` in `frontend/src/views/Sites/SiteEditor.vue`.

**Variables:**
- Python local variables stay `snake_case` and use descriptive domain names like `site_root`, `current_user`, `workflow_run_id`, and `provider_auth_logs`.
- Vue state and derived values use `camelCase`, such as `showCreateDialog`, `fileBrowserSite`, `previewNonce`, and `taskHistory`.
- Constants use `UPPER_SNAKE_CASE`, such as `SITE_PORT_START` and `TASK_WORKFLOW_STAGE_RULES` in `backend/services/site_service.py` and `frontend/src/views/Sites/SiteEditor.vue`.

**Types:**
- Python models, schemas, and enums are named as nouns or response/request shapes, such as `Site`, `SiteResponse`, `TokenResponse`, and `SiteStatus`.
- Frontend interface names mirror backend DTOs and remain singular, such as `Site`, `Task`, `TaskLog`, and `TaskPayload` in `frontend/src/types/models.ts` and `frontend/src/api/tasks.ts`.

## Code Style

**Formatting:**
- Python files follow standard PEP 8 layout with explicit imports, type hints, and small service methods in `backend/services/*` and `backend/api/*`.
- Frontend code uses `<script setup lang="ts">` in Vue SFCs and keeps template logic inline only when it remains simple, as seen in `frontend/src/views/Sites/SiteList.vue` and `frontend/src/views/Auth/Login.vue`.
- Indentation is two spaces in Vue/TypeScript files and four spaces in Python files.
- Trailing semicolons are generally omitted in frontend source files; existing code relies on the project formatter style already present in `frontend/src/**/*.ts` and `frontend/src/**/*.vue`.

**Linting:**
- TypeScript strictness is enforced in `frontend/tsconfig.node.json` and mostly relaxed in `frontend/tsconfig.app.json` for application code that still relies on `// @ts-nocheck`.
- `frontend/vite.config.ts` uses the `@/` alias via `resolve(__dirname, 'src')`; new frontend code should import through that alias rather than deep relative paths.
- Backend quality gates are not enforced by a dedicated linter config in the inspected files; style is maintained through module boundaries, typing, and test coverage.

## Import Organization

**Order:**
1. Standard library imports.
2. Third-party framework and library imports.
3. Local project imports.
4. Type-only imports follow the same group as the module they describe.

**Path Aliases:**
- Frontend code uses `@/*` mapped to `frontend/src/*` in `frontend/tsconfig.json` and `frontend/tsconfig.app.json`.
- Backend code uses absolute package imports like `from backend.services.site_service import site_service` and `from backend.core.config import get_settings` instead of relative imports.

## Error Handling

**Patterns:**
- Backend routes and services raise `HTTPException` with explicit status codes and human-readable `detail` strings, such as `backend/api/v2/sites.py`, `backend/api/deps.py`, and `backend/services/site_service.py`.
- Validation failures are surfaced early; `backend/utils/validation.py` rejects invalid site IDs, and `backend/core/security.py` rejects invalid tokens before business logic executes.
- Frontend API failures are normalized in `frontend/src/api/client.ts`, which maps HTTP status codes to toasts and redirects on `401`.
- Vue page components usually catch request failures locally and either show a toast or an inline message, as in `frontend/src/views/Auth/Login.vue` and `frontend/src/views/Sites/SiteEditor.vue`.

## Logging

**Framework:** `logging` in Python; `vue-sonner` toasts in the browser.

**Patterns:**
- Server-side code logs operational events through `logging.getLogger('uvicorn.error')` in `backend/main.py` and task/service log appenders in `backend/services/task_service.py`.
- Task execution status is written into persistent task logs via `backend/services/task_service.py`, then streamed to clients through WebSocket events.
- Frontend user feedback is handled with `toast.success()`, `toast.warning()`, and `toast.error()` from `vue-sonner`, especially in `frontend/src/api/client.ts`, `frontend/src/views/Auth/Login.vue`, and `frontend/src/views/Sites/SiteList.vue`.

## Comments

**When to Comment:**
- Comments are used for operational intent, not for obvious syntax. Typical comments explain integration behavior, fallback logic, or UI sections, as in `backend/services/task_service.py` and `frontend/src/views/Sites/SiteEditor.vue`.
- Chinese comments are present in UI and service code; keep them concise and tied to the surrounding code path.

**JSDoc/TSDoc:**
- JSDoc/TSDoc is not used broadly in the inspected code.
- Prefer clear names and small functions over inline documentation unless behavior is non-obvious.

## Function Design

**Size:**
- Keep route handlers thin and move business logic into services, following `backend/api/v2/sites.py` calling into `backend/services/site_service.py`.
- Prefer focused service methods that do one job, such as `resolve_site_path()`, `list_site_files()`, `read_site_file()`, and `serialize_site()` in `backend/services/site_service.py`.
- In Vue, keep event handlers and computed values short enough to fit inside one component section; large workflows belong in composables or dedicated components.

**Parameters:**
- Use explicit keyword-like payload fields in API handlers and service calls. `backend/api/v2/sites.py` consumes request dictionaries and normalizes them before calling `site_service.create_site()`.
- Favor typed payload interfaces in frontend API modules, such as `SiteCreateRequest`, `SiteUpdateRequest`, and `TaskPayload`.

**Return Values:**
- Backend endpoints return JSON objects with an `ok` flag plus resource-specific fields, for example `{"ok": True, "site": ...}` in `backend/api/v2/sites.py`.
- Frontend API helpers should return the backend response shape directly through `frontend/src/api/client.ts`, which unwraps Axios responses to `response.data`.

## Module Design

**Exports:**
- Backend packages expose service singletons like `site_service` and `task_service` from their module files, for example `backend/services/site_service.py` and `backend/services/task_service.py`.
- Frontend API modules export plain objects of methods, such as `sitesAPI` in `frontend/src/api/sites.ts` and `tasksAPI` in `frontend/src/api/tasks.ts`.
- Vue components import from `@/components/ui/*` and other project-local modules rather than reimplementing primitives.

**Barrel Files:**
- Barrel files exist in several backend and UI directories, including `backend/api/v2/__init__.py`, `backend/services/__init__.py`, and `frontend/src/components/ui/*/index.ts`.
- When adding new UI primitives or grouped exports, follow the existing `index.ts` pattern used under `frontend/src/components/ui/`.

## Frontend-Specific Conventions

- Prefer the Composition API with `<script setup lang="ts">`.
- Use `ref()` for mutable state, `computed()` for derived values, and `onMounted()`/`onUnmounted()` for lifecycle hooks, as seen in `frontend/src/views/Sites/SiteEditor.vue`.
- Keep router navigation in page components and shared request logic in `frontend/src/api/*`.
- Use `window.confirm()` only for lightweight confirmation flows already present in `frontend/src/views/Sites/SiteList.vue`; prefer dialog components for richer workflows.
- Preserve the current mixed pattern of strongly typed and permissive files: some files intentionally use `// @ts-nocheck` (`frontend/src/api/client.ts`, `frontend/src/views/Sites/SiteEditor.vue`) while the rest of the app stays TypeScript-first.

## Backend-Specific Conventions

- Keep FastAPI route modules declarative and delegate work into services.
- Use `Depends(get_db)` and `Depends(get_current_user)` for request-scoped resources, as in `backend/api/v2/auth.py` and `backend/api/v2/sites.py`.
- Prefer `HTTPException` over custom error return payloads for invalid user input, missing resources, and permission failures.
- When introducing new persistence behavior, keep ORM access in `backend/services/*` and model definitions in `backend/models/*`.

---

*Convention analysis: 2026-04-20*