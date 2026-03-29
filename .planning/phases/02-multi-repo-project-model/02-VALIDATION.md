---
phase: 2
slug: multi-repo-project-model
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-23
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio (backend) / Playwright (E2E) |
| **Config file** | `backend/tests/conftest.py` |
| **Quick run command** | `cd backend && python -m pytest tests/ -v` |
| **Full suite command** | `cd backend && python -m pytest tests/ -v && cd ../frontend && npm run build` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/ -v`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -v && cd ../frontend && npm run build`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | PROJ-01 | — | N/A | unit | `pytest tests/test_projects.py::test_create_project` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | PROJ-02 | — | N/A | unit | `pytest tests/test_projects.py::test_site_project_id_nullable` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | PROJ-01 | — | N/A | unit | `pytest tests/test_projects.py::test_cascade_delete` | ❌ W0 | ⬜ pending |
| 02-01-04 | 01 | 1 | PROJ-02 | — | N/A | manual | `alembic upgrade head && alembic downgrade -1` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | PROJ-03 | — | N/A | unit | `pytest tests/test_projects.py::test_create_blank_repo` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | PROJ-04 | — | N/A | unit | `pytest tests/test_projects.py::test_clone_from_local_git_url` | ❌ W0 | ⬜ pending |
| 02-02-03 | 02 | 2 | PROJ-04 | T-02-01 | Path traversal blocked | unit | `pytest tests/test_projects.py::test_repo_file_path_escape_blocked` | ❌ W0 | ⬜ pending |
| 02-02-04 | 02 | 2 | PROJ-03 | — | N/A | unit | `pytest tests/test_projects.py::test_repo_files_api` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 3 | PROJ-05 | — | N/A | build | `cd frontend && npm run build` | ✅ | ⬜ pending |
| 02-03-02 | 03 | 3 | PROJ-01 | — | N/A | manual | Navigate to /projects, verify list renders | — | ⬜ pending |
| 02-04-01 | 04 | 4 | PROJ-05 | — | N/A | manual | Switch repo tabs, verify file tree updates | — | ⬜ pending |
| 02-04-02 | 04 | 4 | PROJ-05 | — | N/A | manual | Open files from multiple repos, check tab labels | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_projects.py` — stubs for PROJ-01 through PROJ-05
- [ ] Extend `backend/tests/conftest.py` — project fixtures (create_project, create_repo)

*Existing test infrastructure (pytest + httpx + conftest.py) covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Project list card layout | PROJ-01 | Visual UI verification | Navigate /projects, check card grid with name, repo count, last activity |
| Repo tab switching in editor | PROJ-05 | Complex UI state interaction | Open project with 2+ repos, switch tabs, verify file tree + open tabs |
| Monaco multi-tab repo prefix | PROJ-05 | Visual label format check | Open files from different repos, verify `[repo_name] path` format |
| Clone progress WebSocket | PROJ-04 | Requires full stack + real git clone | Add repo via URL, observe clone progress indicator |
| Sidebar navigation update | PROJ-01 | Visual verification | Check sidebar shows "项目管理" instead of "站点管理" |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
