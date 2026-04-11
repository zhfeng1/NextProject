---
phase: 02-multi-repo-project-model
plan: 03
subsystem: ui
tags: [vue3, pinia, typescript, router, shadcn-vue]

requires:
  - phase: 02-multi-repo-project-model
    provides: Project REST API (CRUD + addRepo + file browsing)
provides:
  - Project/ProjectCreateRequest/RepoAddRequest TypeScript types
  - projectsAPI client covering all Projects API endpoints
  - useProjectStore Pinia store
  - ProjectList.vue and ProjectDetail.vue pages
  - /projects routes with /sites redirect
  - Sidebar navigation updated to "项目管理"
affects: [02-04-project-editor]

tech-stack:
  added: []
  patterns: [project store pattern matching site store, card grid layout for projects]

key-files:
  created:
    - frontend/src/api/projects.ts
    - frontend/src/stores/project.ts
    - frontend/src/views/Projects/ProjectList.vue
    - frontend/src/views/Projects/ProjectDetail.vue
  modified:
    - frontend/src/types/models.ts
    - frontend/src/router/index.ts
    - frontend/src/components/Layout/AppLayout.vue

key-decisions:
  - "Kept Globe icon import in AppLayout for backward compat, added FolderKanban for projects menu item"
  - "Sites routes (/:id, /:id/edit) preserved for SiteEditor backward compatibility"
  - "ProjectEditor route deferred to Plan 04 to avoid build failure on missing component"

patterns-established:
  - "Project store follows same pattern as site store (state/actions, no getters needed yet)"
  - "projectsAPI mirrors sitesAPI structure for consistency"

requirements-completed: [PROJ-01, PROJ-02, PROJ-03, PROJ-04, PROJ-05]

duration: 8min
completed: 2026-04-23
---

# Phase 02 Plan 03: 项目管理前端 — 列表、创建、路由、导航 Summary

**Vue3 前端项目管理页面完整实现：TypeScript 类型定义、API 客户端、Pinia store、ProjectList/ProjectDetail 页面、路由配置及侧边栏导航更新**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-23T07:25:00Z
- **Completed:** 2026-04-23T07:33:00Z
- **Tasks:** 7
- **Files modified:** 7

## Accomplishments
- Project/ProjectCreateRequest/RepoAddRequest TypeScript 类型定义，Site 接口添加 project_id
- projectsAPI 客户端覆盖所有 Projects v2 API 端点（list/create/get/update/delete/addRepo/listRepoFiles/getRepoFile）
- useProjectStore Pinia store 实现 fetchProjects/fetchProject/createProject/deleteProject/addRepo
- ProjectList.vue 展示项目卡片网格 + 搜索过滤 + 创建对话框
- ProjectDetail.vue 展示项目信息 + 仓库列表 + 添加仓库对话框（含 git 凭据）
- /projects 路由 + /sites 重定向 + sites/:id/edit 保留兼容
- 侧边栏从"站点管理/我的站点"更新为"项目管理/我的项目"

## Task Commits

Each task was committed atomically:

1. **Task 01: 添加 Project TypeScript 类型** - `52f0920` (feat)
2. **Task 02: 创建 projects API 客户端** - `2664b49` (feat)
3. **Task 03: 创建 project Pinia store** - `ee68e88` (feat)
4. **Task 04: 创建 ProjectList.vue** - `d02f5ac` (feat)
5. **Task 05: 创建 ProjectDetail.vue** - `4288085` (feat)
6. **Task 06: 更新路由配置** - `772956b` (feat)
7. **Task 07: 更新侧边栏导航** - `a75837c` (feat)

## Files Created/Modified
- `frontend/src/types/models.ts` - 添加 Project/ProjectCreateRequest/RepoAddRequest 接口 + Site.project_id
- `frontend/src/api/projects.ts` - Projects API 客户端
- `frontend/src/stores/project.ts` - Project Pinia store
- `frontend/src/views/Projects/ProjectList.vue` - 项目列表页面
- `frontend/src/views/Projects/ProjectDetail.vue` - 项目详情页面
- `frontend/src/router/index.ts` - 添加 /projects 路由 + /sites 重定向
- `frontend/src/components/Layout/AppLayout.vue` - 侧边栏导航更新

## Decisions Made
- 保留 sites/:id 和 sites/:id/edit 路由，SiteEditor 仍在使用
- ProjectEditor 路由不在此处注册，等 Plan 04 创建 ProjectEditor.vue 后一起注册
- 使用 FolderKanban 图标替代 Globe 图标用于项目菜单项

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 前端项目管理页面已完成，可供 Plan 04 (ProjectEditor) 使用
- ProjectDetail.vue 已预留"打开编辑器"按钮，指向 /projects/:id/edit
- 该路由将在 Plan 04 中注册

---
*Phase: 02-multi-repo-project-model*
*Completed: 2026-04-23*
