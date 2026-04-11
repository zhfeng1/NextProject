---
phase: 02-multi-repo-project-model
plan: 02
subsystem: api, services, tasks
tags: [fastapi, celery, sqlalchemy, git-clone, encryption, path-traversal]

requires:
  - phase: 02-multi-repo-project-model/plan-01
    provides: Project model, Site.project_id FK, TaskType.CLONE_REPO enum

provides:
  - ProjectService CRUD + add_repo + path management
  - Projects REST API (GET/POST/PUT/DELETE + repos + file browsing)
  - clone_repo Celery task with async git clone
  - SiteService override_root support for project-grouped repos

affects: [03-ai-coding-engine, 05-docker-deploy]

tech-stack:
  added: []
  patterns: [project-grouped-repos, override_root-pattern, repo-name-validation]

key-files:
  created:
    - backend/services/project_service.py
    - backend/tasks/clone_repo.py
    - backend/api/v2/projects.py
  modified:
    - backend/services/site_service.py
    - backend/services/task_service.py
    - backend/api/__init__.py
    - backend/tests/test_projects.py

key-decisions:
  - "Used encrypt_api_key/decrypt_api_key instead of encrypt_value/decrypt_value — matches existing encryption API"
  - "Changed resolve_site_path to return (root, target) tuple for override_root support"
  - "Used payload_json field (not payload) to match actual AgentTask model schema"

patterns-established:
  - "override_root pattern: pass custom root path to SiteService methods for project-grouped repos"
  - "validate_repo_name: strict alphanumeric+hyphen+underscore+dot regex for repo names"

requirements-completed: [PROJ-01, PROJ-02, PROJ-03, PROJ-04, PROJ-05]

duration: 16min
completed: 2026-04-23
---

# Plan 02-02: 仓库创建与导入 — ProjectService + API + Celery 异步克隆 Summary

**ProjectService CRUD + REST API + clone_repo Celery 任务 + 文件浏览 override_root 支持 + 路径穿越/越权访问防护**

## Performance

- **Duration:** 16 min
- **Started:** 2026-04-23T07:05:15Z
- **Completed:** 2026-04-23T07:21:40Z
- **Tasks:** 9 completed
- **Files modified:** 7

## Accomplishments
- ProjectService 实现完整 CRUD + add_repo（空白创建 + git clone 异步任务）
- Projects REST API 端点完整覆盖（CRUD + 仓库管理 + 文件浏览）
- clone_repo Celery 任务：Redis 锁 + 加密密码解密 + 状态更新
- SiteService 全面支持 override_root（ensure_site_structure, clone_site_repository, list_site_files, read_site_file）
- 安全防护：repo_name 校验防路径注入 + git_password 加密存储 + 文件浏览越权访问拦截

## Task Commits

Each task was committed atomically:

1. **Task 02-02-01: 创建 ProjectService 服务层** - `fa8c9fb` (feat)
2. **Task 02-02-02: 修改 SiteService 支持 override_root 参数** - `211701b` (feat)
3. **Task 02-02-03: 创建 clone_repo Celery 任务** - `0939bb7` (feat)
4. **Task 02-02-04: 修改 SiteService.clone_site_repository 支持 override_root** - `995b213` (feat)
5. **Task 02-02-05: TaskService 注册 clone_repo 任务入队** - `26f648d` (feat)
6. **Task 02-02-06: 创建 Projects API 路由** - `6b493f4` (feat)
7. **Task 02-02-07: 注册 Projects 路由到 API Router** - `443415c` (feat)
8. **Task 02-02-08: 修改 SiteService 文件浏览方法支持 override_root** - `9a4ee1a` (feat)
9. **Task 02-02-09: 扩展 test_projects.py 测试** - `06885d8` (test)

## Files Created/Modified
- `backend/services/project_service.py` - ProjectService: CRUD + add_repo + path management + repo name validation
- `backend/tasks/clone_repo.py` - clone_repo Celery task: async git clone with Redis lock
- `backend/api/v2/projects.py` - Projects REST API routes with file browsing
- `backend/services/site_service.py` - Added override_root to ensure_site_structure, clone_site_repository, list_site_files, read_site_file
- `backend/services/task_service.py` - Registered clone_repo in SUPPORTED_TASK_TYPES and enqueue_task
- `backend/api/__init__.py` - Registered projects router
- `backend/tests/test_projects.py` - 14 test cases including security tests

## Decisions Made
- Used `encrypt_api_key`/`decrypt_api_key` instead of plan's `encrypt_value`/`decrypt_value` — matches existing encryption API in `backend/core/encryption.py`
- Used `payload_json` field instead of `payload` — matches actual `AgentTask` model schema
- Changed `resolve_site_path` return type to `tuple[Path, Path]` (root, target) to support override_root while maintaining path traversal checks

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] encryption function names differ from plan**
- **Found during:** Task 02-02-01 (ProjectService)
- **Issue:** Plan specified `encrypt_value`/`decrypt_value` but actual codebase uses `encrypt_api_key`/`decrypt_api_key`
- **Fix:** Used actual function names from `backend/core/encryption.py`
- **Files modified:** backend/services/project_service.py, backend/tasks/clone_repo.py
- **Verification:** Tests pass, encryption/decryption works correctly

**2. [Rule 1 - Bug] AgentTask uses payload_json not payload**
- **Found during:** Task 02-02-01 and 02-02-03
- **Issue:** Plan used `task.payload` but actual AgentTask model has `payload_json` field
- **Fix:** Used `payload_json` throughout
- **Files modified:** backend/services/project_service.py, backend/tasks/clone_repo.py
- **Verification:** All tests pass

---

**Total deviations:** 2 auto-fixed (2 bugs from plan-reality mismatch)
**Impact on plan:** Both fixes were necessary for correctness. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ProjectService + API 完整可用，前端可开始集成项目管理 UI
- clone_repo 任务可在 Celery worker 中执行异步 git 克隆
- 文件浏览 API 支持 project-grouped 路径
- Ready for Plan 02-03 (if exists) or next phase

---
*Phase: 02-multi-repo-project-model*
*Completed: 2026-04-23*
