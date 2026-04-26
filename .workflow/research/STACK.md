# Stack Research

## Overview

NextProject already sits on a mainstream control-plane stack for an AI-driven multi-site platform: FastAPI + SQLAlchemy + PostgreSQL for APIs and metadata, Celery + Redis for long-running jobs, MinIO for artifacts, and Vue 3 + Vite + Pinia for the operator UI. For this product category, the main standard alternatives would be a TypeScript-first stack such as NestJS/BullMQ/Prisma on the backend and React/Next.js on the frontend, but the current Python-first direction is the better brownfield fit because the repo already centers on Python task orchestration, CLI-agent execution, WebSockets, and containerized workers. Official docs still support the core choices: FastAPI emphasizes high performance, typing, OpenAPI, and WebSockets; Vue emphasizes progressive adoption and SPA scalability; Celery remains the standard Python queue for retries, scheduling, and queue routing. The near-term opportunity is stack convergence rather than stack replacement.

## Current Stack Fit

- **Backend API/control plane: strong fit.** `main_service/requirements.txt` pins `fastapi==0.116.1`, `sqlalchemy==2.0.43`, `pydantic==2.11.7`, and the app actively uses async APIs plus WebSockets in `backend/main.py` and `backend/api/v2/websocket.py`. This matches FastAPI's documented strengths around typed APIs, OpenAPI, and WebSocket support.
- **Data layer: good fit, but needs stricter production discipline.** `docker-compose.yml` uses PostgreSQL in runtime, `backend/core/database.py` is tuned for async Postgres, and `backend/alembic/` exists for migrations. However, `backend/main.py` still performs `create_all()` and ad hoc `ALTER TABLE` logic at startup, so the standard stack is present but not yet cleanly enforced.
- **Async work: strong fit.** `backend/core/celery_app.py` separates queues for AI tasks, deploy tasks, and test tasks; `docker-compose.yml` includes Redis, Celery worker, Celery beat, and Flower. That is a standard and well-matched pattern for long-running, retryable jobs that should not block request handling.
- **Artifact/template/version storage: strong fit.** `backend/utils/minio.py` plus `backend/services/template_service.py` and `backend/services/version_service.py` show MinIO being used as S3-compatible object storage for platform assets. This is a solid choice for generated artifacts and version payloads.
- **Frontend/admin console: strong fit.** `frontend/package.json` shows Vue 3, Vite 8, Pinia, Vue Router, Zod, Vee-Validate, Monaco Editor, and charting libs; `frontend/src/main.ts` and `frontend/src/router/index.ts` confirm a standard SPA admin-console shape. Vue's progressive model is a good match for a brownfield operator interface.
- **Testing stack: partial but sensible fit.** Backend tests are established with `pytest`, `pytest-asyncio`, and HTTPX (`backend/tests/conftest.py`). Frontend has Playwright configured (`frontend/playwright.config.ts`) and Vitest installed, but only a small visible E2E surface so far (`frontend/tests/e2e/site-creation.spec.ts`).
- **Operations stack: good near-term fit.** Docker Compose, Prometheus, Grafana, and Flower in `docker-compose.yml` are appropriate for current-stage deployment and observability. This is strong for a brownfield product team, even if it is not yet a fully mature multi-tenant production platform.

## Recommended Near-Term Stack Focus

1. **Stay on FastAPI + SQLAlchemy 2 + PostgreSQL + Alembic as the primary backend platform.** This is already the best fit for a Python-heavy orchestration product; avoid a backend rewrite. Near-term focus should be making Alembic the only production schema migration path.
2. **Keep Celery + Redis for AI, deploy, and test workloads.** The current queue split maps well to the domain and is more proven for Python background work than swapping to lighter alternatives unless product scope shrinks dramatically.
3. **Keep Vue 3 + Vite + Pinia for the console, but standardize the UI layer.** The repo currently points to Tailwind/Radix/Reka-style primitives while `frontend/vite.config.ts` still references `ElementPlusResolver`; pick one primary UI system and remove the other integration path.
4. **Use Playwright as the primary user-flow regression layer; add Vitest selectively.** For this product, end-to-end flows across auth, site management, task execution, and deployment are more valuable than a large unit-test-first frontend strategy. Vitest should support stores, API clients, and utility logic where it adds speed.
5. **Keep Docker Compose as the default platform environment for now.** Compose matches the current repo shape and team velocity. Stronger orchestration such as Kubernetes should be treated as a later operational decision, not a prerequisite for the next phase.

## Risks/Tradeoffs

- **Migration split-brain risk.** `backend/alembic/env.py` exists, but `backend/main.py` also creates tables and mutates schema on startup. That increases environment drift and makes production behavior harder to reason about.
- **Test/runtime database drift.** Runtime is PostgreSQL in `docker-compose.yml`, while tests default to SQLite in `backend/tests/conftest.py`. That keeps tests cheap, but can hide SQL and transaction differences.
- **Frontend stack drift.** `frontend/package.json` reflects a Tailwind/Radix/Reka-oriented UI direction, but `frontend/vite.config.ts` still wires `ElementPlusResolver`. Mixed UI strategies increase maintenance cost and bundle uncertainty.
- **Heavy service image tradeoff.** `main_service/Dockerfile` bundles Python, Node, Playwright, Docker CLI, and agent tooling into one runtime image. This is pragmatic for the current platform, but it increases image size, attack surface, and upgrade coordination cost.
- **Compose-first operational ceiling.** The current ops stack is effective for local deployment and small-team operations, but higher isolation, HA, auditability, and tenant separation may eventually require a more formal runtime model.

