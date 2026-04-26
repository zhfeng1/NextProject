---
title: "Test Conventions"
readMode: required
priority: high
category: test
keywords:
  - test
  - coverage
  - mock
  - fixture
  - assertion
  - framework
---
# Test Conventions

Auto-generated from project analysis. Update manually as patterns evolve.

## Framework
- Framework: backend uses pytest / pytest-asyncio; frontend has Playwright e2e tests; Vitest is installed but not yet established as a repo convention
- Run command: backend via `pytest` (coverage configured in `pytest.ini`); frontend e2e via Playwright scripts/tooling as configured in `frontend/`

## Directory Structure
- Pattern: backend tests live in `backend/tests/`; frontend browser tests live in `frontend/tests/e2e/`

## Naming Conventions
- Backend test files: `test_*.py`
- Frontend e2e files: `*.spec.ts`

## Patterns
- Backend tests use `@pytest.mark.asyncio` and shared fixtures from `backend/tests/conftest.py`
- Assertions are direct `assert` checks against HTTP status codes and JSON payloads
- Test scope currently centers on auth, sites, CORS, MinIO, and AI center APIs
- Prefer extending existing fixture style instead of introducing a new test harness

## Manual Additions
- For backend API changes, add or update pytest coverage near the touched route/service path
- For user-visible frontend flows, prefer at least one end-to-end verification on the golden path
