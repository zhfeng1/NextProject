# Codebase Concerns

**Analysis Date:** 2026-04-20

## Tech Debt

**Secret handling is mixed with application state:**
- Issue: Sensitive credentials are stored in plain text models and then returned by API responses without redaction.
- Files: `docker-compose.yml`, `backend/core/config.py`, `backend/models/app_config.py`, `backend/models/user_config.py`, `backend/models/user_llm_provider.py`, `backend/api/v2/providers.py`, `backend/services/auth_service.py`, `backend/main.py`
- Impact: API keys, access tokens, and default credentials can leak into browser memory, network traces, logs, backups, and support exports.
- Fix approach: Remove all non-test default secrets, encrypt secret fields at rest, and make response serializers omit secret material unless an explicit admin-only workflow requires it.

**Runtime depends on the host Docker daemon:**
- Issue: The main application and worker containers mount `/var/run/docker.sock`, which gives the app control over the host Docker engine.
- Files: `docker-compose.yml`, `backend/services/container_service.py`
- Impact: Any compromise of the backend or task runner can become host-level container control, which is effectively root-equivalent on the machine.
- Fix approach: Replace the socket mount with a dedicated builder service or remote daemon, and keep the app container unprivileged.

**Site execution is coupled to local subprocesses:**
- Issue: Generated sites are started with `subprocess.Popen` on the host, while task execution also shells out to provider CLIs and custom commands.
- Files: `backend/services/site_service.py`, `backend/services/task_service.py`, `backend/services/container_service.py`, `backend/api/v2/sites.py`
- Impact: Untrusted or buggy generated code can consume host resources, hang processes, or access local files outside the intended site boundary.
- Fix approach: Run generated sites inside isolated containers or supervised sandboxes with explicit CPU, memory, and filesystem limits.

## Security Considerations

**User-controlled shell and repository inputs create a high-risk execution surface:**
- Issue: Task execution accepts free-form command text, and site creation can clone and run arbitrary repositories and start commands.
- Files: `backend/services/task_service.py`, `backend/services/site_service.py`, `backend/api/v2/sites.py`
- Impact: A malicious or compromised user account can trigger remote code execution, data exfiltration, or lateral movement through the build/runtime environment.
- Fix approach: Restrict commands to an allowlist, validate repository sources, and execute builds in disposable containers or VMs instead of the app host.

**Model-fetch endpoints can be used as SSRF primitives:**
- Issue: `/api/llm-models` and `/api/v2/providers/fetch-models` accept an arbitrary base URL and then request `/models` from it.
- Files: `backend/main.py`, `backend/api/v2/providers.py`
- Impact: An authenticated user can probe internal services, metadata endpoints, or other network-only targets reachable from the backend.
- Fix approach: Allow only approved hosts and schemes, add egress restrictions, and validate base URLs before making outbound requests.

**Secret-bearing configuration is exposed to clients:**
- Issue: Configuration endpoints return provider keys, LLM keys, and OAuth tokens verbatim.
- Files: `backend/main.py`, `backend/services/auth_service.py`, `backend/api/v2/providers.py`
- Impact: Browser-side code and browser extensions can observe secrets that should remain server-side only.
- Fix approach: Split configuration into public and secret subsets, return masked values only, and add dedicated secret-update endpoints that never echo the secret back.

**Docker-compose defaults ship known credentials if operators do not override them:**
- Issue: Compose defaults include database, Redis, MinIO, Flower, and Grafana credentials in the service definitions.
- Files: `docker-compose.yml`, `backend/core/config.py`
- Impact: A fresh deployment without an external secret store inherits predictable credentials and a weak baseline secret posture.
- Fix approach: Require explicit secret injection for production and fail fast when any non-test credential is missing.

## Performance Bottlenecks

**Task log writes are chatty and unbounded:**
- Issue: `append_log()` inserts a row and commits on every log line, then publishes over Redis for each message.
- Files: `backend/services/task_service.py`, `backend/services/websocket_service.py`
- Impact: Long-running tasks generate heavy write amplification, and the task log table grows indefinitely without retention or pruning.
- Fix approach: Batch log persistence, add retention policies, and periodically prune old task logs.

**Health checks perform full dependency probes on every request:**
- Issue: The health endpoint pings the database, Redis, and MinIO each time it is called.
- Files: `backend/main.py`, `docker-compose.yml`
- Impact: Frequent container health checks can create avoidable load spikes and make transient dependency issues look like app outages.
- Fix approach: Separate lightweight liveness from deeper readiness checks and cache expensive probes for a short interval.

**Host-run site processes have no explicit resource isolation:**
- Issue: Local preview sites are launched with `Popen` and inherit the host environment, but they are not constrained by cgroups or container limits.
- Files: `backend/services/site_service.py`
- Impact: A generated site can monopolize CPU, memory, file descriptors, or child processes on the host.
- Fix approach: Move previews into isolated containers or attach them to a process supervisor with quotas and timeouts.

## Fragile Areas

**Schema bootstrapping happens inside application startup:**
- Issue: Startup code creates tables and performs ad hoc column additions with raw SQL instead of relying only on migration tooling.
- Files: `backend/main.py`, `backend/alembic/versions/20260320_0001_initial_v2_schema.py`, `backend/alembic/versions/20260323_0002_add_user_configs.py`, `backend/alembic/versions/20260323_0003_user_config_add_provider_keys.py`, `backend/alembic/versions/20260323_0004_add_user_llm_providers.py`
- Impact: Multiple replicas starting together can race on schema mutation, and production schema state becomes harder to audit.
- Fix approach: Move all schema changes into Alembic migrations and keep startup limited to non-destructive bootstrap checks.

**Process and log state lives only in memory:**
- Issue: Site process tracking, provider-auth subprocesses, and websocket connection tracking are stored in process-local dictionaries.
- Files: `backend/services/site_service.py`, `backend/main.py`, `backend/services/websocket_service.py`
- Impact: Restarts lose operational state, and horizontal scaling breaks because one worker cannot see another worker’s in-memory state.
- Fix approach: Externalize process coordination and task-log fanout through Redis or a dedicated orchestration service.

**Reverse proxying to sub-sites trusts backend state too much:**
- Issue: Preview and site proxy routes forward requests and upstream headers to per-site internal URLs with little additional policy enforcement.
- Files: `backend/main.py`
- Impact: Unexpected upstream behavior can leak headers, create confusing redirects, or surface internal site failures as opaque proxy errors.
- Fix approach: Keep proxying scoped to validated internal ports, add strict header policy, and cap upstream response size and timeout behavior.

**Custom Dockerfiles are generated from repository contents:**
- Issue: `container_service` writes a fallback Dockerfile when one is absent, and then builds the repo directly.
- Files: `backend/services/container_service.py`
- Impact: Repository contents control the final runtime image, which increases the blast radius of a compromised or malformed site repo.
- Fix approach: Use a curated base image and explicit build steps rather than deriving execution behavior from arbitrary repo files.

## Test Coverage Gaps

**High-risk execution paths need direct coverage:**
- What's not tested: provider auth process management, raw command execution, proxy forwarding, and host-process lifecycle handling.
- Files: `backend/services/task_service.py`, `backend/services/site_service.py`, `backend/main.py`, `backend/api/v2/providers.py`
- Risk: Regressions in the most dangerous code paths can ship without feedback because the current tests focus mainly on auth and site CRUD.
- Priority: High

**Secret exposure behavior is not asserted:**
- What's not tested: whether secret-bearing fields are masked or omitted from `/api/config`, provider APIs, and user-config endpoints.
- Files: `backend/main.py`, `backend/api/v2/providers.py`, `backend/services/auth_service.py`
- Risk: A future change can accidentally broaden the public secret surface.
- Priority: High

**Network-abuse guards are missing:**
- What's not tested: SSRF resistance for model-fetch endpoints and validation of external base URLs.
- Files: `backend/main.py`, `backend/api/v2/providers.py`
- Risk: Internal network probing can remain unnoticed until deployment.
- Priority: Medium

---

*Concerns audit: 2026-04-20*
