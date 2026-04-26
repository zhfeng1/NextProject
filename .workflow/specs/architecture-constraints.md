---
title: "Architecture Constraints"
readMode: required
priority: high
category: planning
keywords:
  - architecture
  - module
  - layer
  - boundary
  - dependency
---
# Architecture Constraints

Auto-generated from project structure. Update manually as architecture evolves.

## Module Structure
- Type: monorepo
- Key modules:
  - `backend/` — FastAPI API, services, models, tasks, tests
  - `frontend/` — Vue 3 application and UI
  - `docs/` — requirement and planning docs
  - `main_service/` — container/runtime assets for the main backend service
  - `monitoring/` — monitoring-related configuration
  - `k8s/` — deployment manifests scaffold

## Layer Boundaries
- Backend request flow should stay: `api` → `services` → `models/schemas/core/utils`
- Long-running or asynchronous work belongs in Celery tasks / task services, not directly inside route handlers
- Frontend page-level logic belongs in `views/`; reusable UI and interaction blocks belong in `components/` or `composables/`
- Keep API transport logic in `frontend/src/api/` instead of scattering raw HTTP calls across views

## Dependency Rules
- Backend routes should orchestrate and validate, while business logic stays in services
- Services may depend on models, schemas, core config/security/database, and utils
- Frontend views can use stores, api modules, and reusable components; keep cross-view coupling low
- Preserve compatibility between legacy backend flows and `/api/v2` until an explicit deprecation decision is made

## Technology Constraints
- Runtime: Python backend + Node/Vite frontend + Docker Compose infrastructure
- Module system: frontend uses ESM; backend uses standard Python module imports
- Strict mode: frontend TypeScript is currently non-strict (`strict: false`); several files still use `@ts-nocheck`

## Manual Additions
- Prefer brownfield incremental evolution over rewrite
- Favor quality-controlled speed over raw delivery speed
