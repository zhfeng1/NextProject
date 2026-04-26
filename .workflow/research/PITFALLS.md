# NextProject Pitfalls Research

Based on local repo/docs review on 2026-04-20.

## Top Pitfalls

1. **A privileged legacy API surface still bypasses the normal auth model.**
   - `backend/main.py` still serves many legacy `/api/*` routes by resolving a seeded default admin via `get_legacy_user()` rather than the requesting user (`backend/main.py:170-175`, `398-675`).
   - `/api/config` is unauthenticated and returns/saves LLM and Codex secrets (`backend/main.py:346-374`).
   - The default admin is auto-created on startup, and the config still carries a weak default password value (`backend/main.py:120-143`, `backend/core/config.py:84-88`).

2. **AI-generated code is running with host-level power, not true tenant isolation.**
   - `main-service` and `celery-worker` mount `/var/run/docker.sock`, so a compromised task can reach the host Docker daemon (`docker-compose.yml:64-65`, `133-133`).
   - Site startup can execute arbitrary shell via `sh -lc <start_command>` (`backend/services/site_service.py:341-354`, `493-497`).
   - Codex tasks are launched with `--skip-git-repo-check --dangerously-bypass-approvals-and-sandbox` (`backend/services/task_service.py:104-105`, `603-613`).

3. **Brownfield drift is being absorbed at runtime instead of being tightly controlled at release time.**
   - The app creates tables and performs ad hoc column mutations on startup (`backend/main.py:107-114`).
   - Legacy `/api`, v1, and v2 routes all coexist, which increases behavior drift and hidden compatibility burden (`backend/api/__init__.py:10-19`, `backend/main.py:346-675`).
   - Repo docs and runtime entrypoints do not fully agree on ports and readiness: README still points users at `18080`, while Docker exposes frontend on `20100` (`README.md:24-25`, `docker-compose.yml:258-259`).

4. **Some “quality” features are still shallow, so they may create false confidence.**
   - Snapshots are full tarballs of the site tree, and the recorded diff summary is only a file count (`backend/services/version_service.py:53-66`).
   - Rollback deletes the site root, untars blindly, then restarts the preview; there is no integrity check, schema compatibility check, or post-restore verification (`backend/services/version_service.py:90-97`).
   - Template site creation increments usage and records the archive path, but it does not actually unpack/apply the template archive into the site (`backend/services/template_service.py:65-71`).

5. **Coverage is thinnest around the most failure-prone paths.**
   - Existing tests cover auth, CORS, MinIO, sites, and some workflow/center flows, but not the full subprocess task engine, deploy paths, provider auth, websocket authorization, rollback safety, or template application (`backend/tests/test_auth.py`, `backend/tests/test_cors.py`, `backend/tests/test_minio.py`, `backend/tests/test_sites.py`, `backend/tests/test_ai_centers.py`).
   - The websocket log endpoint accepts any connection for any task id and does not check user access (`backend/api/v2/websocket.py:15-89`).
   - A develop task can still finish as `SUCCESS` even when preview restart fails, which weakens trust in task status as a product signal (`backend/services/task_service.py:720-749`).

## Why They Matter Here

- **The product promise is “speed with quality,” not speed alone.** An unauthenticated admin surface or misleading success status undermines trust faster than slow delivery does.
- **This platform executes generated code and external repositories.** Without hard isolation, one bad prompt, malicious repo, or credential leak can affect the whole platform rather than a single site.
- **The target users are broader than engineers.** PMs and non-technical users will assume snapshot, template, monitoring, and task status features are dependable; shallow implementations will feel like broken promises.
- **Brownfield evolution compounds drift.** Every new feature added on top of legacy `/api` + v2 + startup mutation logic makes future debugging, onboarding, and safe release management harder.
- **The riskiest work happens in long-running async flows.** If tasks, rollback, deploy, and realtime logs are not well-tested, platform reliability will erode exactly where users expect the highest leverage.

## Preventive Moves

1. **Fence off the privileged legacy surface immediately.** Require auth on all remaining `/api/*` routes, remove secret-returning public endpoints, rotate defaults, and make `/api/v2` the only supported external contract.
2. **Move generated-code execution into real isolation boundaries.** Remove host Docker socket access from general-purpose services, run site/task execution in constrained per-site runners, and sharply limit shell-based start commands.
3. **Stop mutating schema at app boot.** Make Alembic migrations the only schema-change path, and treat startup seeding as explicit environment setup rather than implicit runtime repair.
4. **Make rollback/template claims match reality before leaning on them in product positioning.** Add snapshot exclusions, restore validation, richer diffs, and actual template archive materialization.
5. **Add test coverage where blast radius is highest.** Prioritize legacy API auth coverage, websocket auth/access control, task subprocess lifecycle, rollback restore verification, deploy paths, and preview-restart failure handling.
6. **Track task truthfulness, not just task completion.** A task should not be considered a clean success if the preview failed to restart or if logs/realtime status cannot be trusted.

## Watchlist

- Requests still hitting **legacy `/api/*`** instead of `/api/v2`.
- Any response path that returns **raw provider secrets/tokens** to the browser.
- Any task whose final result contains **`preview_restart.ok = false`**.
- Websocket subscriptions for task logs without a matching authenticated site/task access check.
- Snapshot/rollback incidents where restore succeeded technically but the site is not actually usable afterward.
- User confusion around **documented ports/features vs actual runtime behavior** (especially `18080` vs `20100`, monitoring, templates, rollback, and realtime logs).
