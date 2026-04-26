---
status: passed
phase: 02-multi-repo-project-model
verified: 2026-04-27
phase_goal: "用户可以创建项目并关联多个 git 仓库，支持微服务和前后端分离架构。"
must_haves_score: 38/38
---

# Phase 02: 多仓库项目模型 — Verification Report (Re-verified 2026-04-27)

## Summary

All 38 must_haves across Plans 01-05 verified against actual codebase. Frontend build passes. Phase goal achieved.

---

## Plan 01: Project + ProjectRepo 数据模型与 Alembic 迁移

| # | Must Have | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `projects` 表模型（name, description, org_id, owner_id, deleted_at） | PASS | `backend/models/project.py:10` — `class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base)` |
| 2 | `sites` 表包含可空 `project_id` FK → `projects.id` | PASS | `backend/models/site.py:26` — `project_id: Mapped[str \| None]` with `ForeignKey("projects.id")` |
| 3 | `TaskType` 枚举包含 `CLONE_REPO` | PASS | `backend/models/enums.py:26` — `CLONE_REPO = "clone_repo"` |
| 4 | Alembic 迁移包含 DDL + 数据迁移 | PASS | `backend/alembic/versions/20260423_0002_add_projects.py` — `op.create_table("projects")` + INSERT/UPDATE |
| 5 | Alembic 迁移包含文件系统迁移 | PASS | `shutil.copytree` + `shutil.rmtree` in migration upgrade |
| 6 | 迁移 downgrade 可回退 | PASS | `def downgrade()` with reverse file migration + `op.drop_table("projects")` |
| 7 | 现有 `test_sites.py` 全部 PASS | PASS | Per 02-01-SUMMARY: all 11 tests passed |

## Plan 02: ProjectService + API + Celery 异步克隆

| # | Must Have | Status | Evidence |
|---|-----------|--------|----------|
| 1 | ProjectService CRUD + add_repo + repo_root | PASS | `backend/services/project_service.py:37` — `class ProjectService` with all methods |
| 2 | Projects API (GET/POST/PUT/DELETE + repos + 文件浏览) | PASS | `backend/api/v2/projects.py:12` — full router |
| 3 | clone_repo Celery 任务 + Redis 锁 | PASS | `backend/tasks/clone_repo.py:14` — `clone_repo_task` with lock acquire/release |
| 4 | clone_repo 使用 `AgentTask` 模型 | PASS | `backend/tasks/clone_repo.py:7` — `from backend.models import AgentTask` |
| 5 | TaskService 注册 clone_repo 入队 | PASS | `backend/services/task_service.py:31` — SUPPORTED_TASK_TYPES + enqueue logic |
| 6 | SiteService override_root 支持 | PASS | `ensure_site_structure`, `clone_site_repository`, `list_site_files`, `read_site_file` — all have `override_root` |
| 7 | 路径穿越防护在 override_root 下生效 | PASS | `resolve_site_path` applies `.resolve()` check with override_root |
| 8 | git_password 加密存储 | PASS | `encrypt_api_key` in project_service.py:191; `decrypt_api_key` in clone_repo.py:44 |
| 9 | repo_name 严格校验 | PASS | `REPO_NAME_PATTERN` + `validate_repo_name` in project_service.py:20,24 |
| 10 | 文件浏览端点校验 site.project_id == project_id | PASS | `api/v2/projects.py:122,140` — ownership check |
| 11 | test_repo_file_path_escape_blocked 测试 | PASS | `backend/tests/test_projects.py:159` |
| 12 | test_repo_files_cross_project_blocked 测试 | PASS | `backend/tests/test_projects.py:192` |
| 13 | 全部 test_projects.py 和 test_sites.py PASS | PASS | Per 02-02-SUMMARY: 14 test cases + 11 site tests all pass |

## Plan 03: 项目管理前端 — 列表、创建、路由、导航

| # | Must Have | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Project/ProjectCreateRequest/RepoAddRequest TypeScript 类型 | PASS | `frontend/src/types/models.ts:50,60,65` |
| 2 | projectsAPI 客户端覆盖所有端点 | PASS | `frontend/src/api/projects.ts:4` — 8 methods |
| 3 | useProjectStore Pinia store | PASS | `frontend/src/stores/project.ts:11` — 5 actions |
| 4 | ProjectList.vue 卡片网格 + 创建对话框 | PASS | File exists with useProjectStore, filteredProjects |
| 5 | ProjectDetail.vue 项目信息 + 仓库列表 + 添加仓库 | PASS | File exists with fetchProject, addRepoForm |
| 6 | /projects 路由 + /sites 重定向 | PASS | `router/index.ts:45,60` — ProjectList + `redirect: '/projects'` |
| 7 | 侧边栏"项目管理/我的项目" | PASS | AppLayout.vue:68 "项目管理", :73 `to="/projects"`, :75 "我的项目"; no "我的站点" found |
| 8 | `npm run build` 编译通过 | PASS | Build succeeds in 3.41s |

## Plan 04: 文件浏览与 Monaco 集成

| # | Must Have | Status | Evidence |
|---|-----------|--------|----------|
| 1 | RepoTabs: Tab 切换 + 克隆中提示 | PASS | `RepoTabs.vue` — `emit('select')`, "克隆中...", `activeRepoId` |
| 2 | RepoFileTree: 文件树 + 仓库切换自动刷新 | PASS | `RepoFileTree.vue` — `listRepoFiles`, `emit('open-file')`, `watch(repoId)` |
| 3 | ProjectEditor 集成 RepoTabs + RepoFileTree + 标签栏 | PASS | `ProjectEditor.vue` — imports + openTabs + handleOpenFile + handleCloseTab |
| 4 | ProjectEditor 路由注册 | PASS | `router/index.ts:55` — `name: 'ProjectEditor'` |
| 5 | 标签格式 `[repo_name] filename` | PASS | `ProjectEditor.vue:91` — `` `[${payload.repoName}] ${filename}` `` |
| 6 | 切换仓库不关闭已打开标签 | PASS | `handleSelectRepo` only sets `activeRepoId`, openTabs untouched |
| 7 | Monaco 只读模式 | PASS | `ProjectEditor.vue:164` — `:readonly="true"` with CodeEditor |
| 8 | `npm run build` 通过 | PASS | Verified |

## Plan 05: UAT Gap Closure

| # | Must Have | Status | Evidence |
|---|-----------|--------|----------|
| 1 | clone_repo_task 注册到 Celery worker | PASS | `celery_app.py:16,34` — include + task_routes; `tasks/__init__.py:4,6` — import + __all__ |
| 2 | 仓库单独删除（API + UI） | PASS | `api/v2/projects.py:100` DELETE; `project_service.py:228` delete_repo; `ProjectDetail.vue` handleDeleteRepo + Trash2 |
| 3 | 编辑器返回按钮 | PASS | `ProjectEditor.vue:117-118` — ArrowLeft + "返回项目" |
| 4 | 空白仓库不生成默认模板 | PASS | `project_service.py:216` — "no template files", mkdir + git init only |
| 5 | Monaco 只读 + 语法高亮 | PASS | `ProjectEditor.vue:161-165` — CodeEditor + `:readonly="true"` + `:language` |
| 6 | 必填项星号标记 | PASS | `ProjectDetail.vue:146` — `<span class="text-destructive">*</span>` |

---

## Requirements Traceability

| REQ-ID | Description | Status | Covered By |
|--------|-------------|--------|------------|
| PROJ-01 | 用户可创建项目并命名和描述 | PASS | Plan 01 (model) + Plan 02 (API) + Plan 03 (frontend) |
| PROJ-02 | 用户可关联多个 git 仓库 | PASS | Plan 01 (FK) + Plan 02 (add_repo) + Plan 03 (detail) |
| PROJ-03 | 用户可创建空白站点 | PASS | Plan 02 (add_repo blank) + Plan 05 (simplified init) |
| PROJ-04 | 用户可通过 git URL 导入仓库 | PASS | Plan 02 (clone_repo_task) + Plan 05 (Celery registration) |
| PROJ-05 | 用户可浏览项目下所有仓库文件 | PASS | Plan 02 (file API) + Plan 04 (ProjectEditor + RepoFileTree) |

## Security Verification

| Check | Status | Evidence |
|-------|--------|----------|
| repo_name 路径注入防护 | PASS | `REPO_NAME_PATTERN` regex validation |
| git_password 加密存储 | PASS | encrypt_api_key/decrypt_api_key |
| 文件浏览路径穿越防护 | PASS | resolve_site_path + test_repo_file_path_escape_blocked |
| 跨项目仓库越权访问防护 | PASS | site.project_id == project_id check + test_repo_files_cross_project_blocked |

## Frontend Build

```
npm run build -> SUCCESS (3.41s, 0 errors)
```

---

## human_verification

以下项目需要人工测试（UI 交互、视觉检查）：

- [ ] 创建项目后在 ProjectList 页面正确显示卡片（名称、描述、仓库数）
- [ ] 点击项目卡片跳转到 ProjectDetail 正确显示仓库列表
- [ ] 添加仓库对话框：必填星号可见、空名称时按钮禁用
- [ ] 添加空白仓库后仓库卡片立即出现、状态正确、无默认模板文件
- [ ] 通过 git URL 添加仓库后显示"克隆中..."状态，克隆完成后状态更新
- [ ] 打开编辑器页面：RepoTabs 切换、文件树加载、点击文件打开标签页
- [ ] 编辑器标签显示 `[repo_name] filename` 格式，关闭标签功能正常
- [ ] 切换仓库 Tab 时已打开的编辑器标签保持不变
- [ ] Monaco 编辑器只读（无法编辑）且有语法高亮
- [ ] 返回按钮点击后正确跳转到 ProjectDetail
- [ ] 删除仓库弹出确认对话框，确认后仓库从列表消失
- [ ] 侧边栏显示"项目管理/我的项目"，点击跳转到 /projects
- [ ] 访问 /sites 自动重定向到 /projects
- [ ] 删除项目后在列表中不再显示
