# Phase 2: 多仓库项目模型 — Research

**Date:** 2026-04-23
**Phase:** 02-multi-repo-project-model
**Requirements:** PROJ-01, PROJ-02, PROJ-03, PROJ-04, PROJ-05

---

## 1. 现有代码架构分析

### 1.1 数据模型层

**Site 模型** (`backend/models/site.py:19-33`)
- 主键 `id` (UUID)，业务 ID `site_id` (String(64), unique)
- FK: `org_id` → organizations, `owner_id` → users, `template_id` → templates
- 字段: name, status, port, root_path, preview_url, internal_url, config(JSONB), deleted_at
- 使用 `UUIDPrimaryKeyMixin` + `TimestampMixin`（定义在 `backend/models/base.py:36-51`）

**Site 被以下表引用（FK 依赖链）：**
- `tasks.site_id` → `sites.id` (CASCADE)
- `site_versions.site_id` → `sites.id` (CASCADE)
- `conversations.site_id` → `sites.id`
- `workflow_runs.site_id` → `sites.id` (CASCADE)
- `site_requirement_events.site_id` → `sites.id` (CASCADE)
- `site_requirement_snapshots.site_id` → `sites.id` (CASCADE)
- `site_skill_bindings.site_id` → `sites.id` (CASCADE)
- `site_deploy_config.site_id` → `sites.site_id` (CASCADE) — 注意：这个用的是 site_id 字符串，不是 UUID
- `site_provider_config.site_id` → `sites.site_id` (CASCADE) — 同上

**关键发现：** `site_deploy_config` 和 `site_provider_config` 用 `sites.site_id`（字符串）做 FK，其他表用 `sites.id`（UUID）做 FK。新增 `project_id` 列时需注意这两个特殊表。

### 1.2 服务层

**SiteService** (`backend/services/site_service.py`)
- 单例 `site_service`，管理站点生命周期
- 文件存储路径: `GENERATED_SITES_ROOT / site_id`（当前路径是 `generated_sites/<site_id>/`）
- 核心方法:
  - `site_root(site_id)` → 文件根路径
  - `ensure_site_structure(site_id)` → 初始化目录 + git init
  - `clone_site_repository(site_id, git_url, ...)` → git clone（同步执行）
  - `list_site_files/read_site_file` → 文件浏览
  - `create_site(...)` → 创建 DB 记录 + 文件系统初始化
  - 启动/停止/重启进程管理

**关键发现：**
1. `clone_site_repository` 当前在 `create_site` 中**同步**执行，D-07 要求改为 Celery 异步任务
2. 文件存储目前是 `generated_sites/<site_id>/`，D-05 要求改为 `generated_sites/<project_id>/<repo_name>/`
3. `ensure_site_structure` 会创建 backend/frontend 目录 + 默认文件 + git init，这是"空白站点"的逻辑

### 1.3 API 层

**Sites API** (`backend/api/v2/sites.py`)
- 路由前缀 `/sites`，CRUD + start/stop/adjust + files + requirements
- 注册在 `backend/api/__init__.py:14`，prefix `/api/v2`
- 响应格式: `{"ok": True/False, ...}`

### 1.4 前端层

**路由** (`frontend/src/router/index.ts`):
- `/sites` → SiteList, `/sites/:id` → SiteDetail, `/sites/:id/edit` → SiteEditor
- 还有兼容重定向 `/site-editor/:id` → SiteEditor

**视图组件：**
- `SiteList.vue` (294行): 卡片网格 + 创建对话框（含 git 克隆表单）
- `SiteEditor.vue` (907行): 核心编辑页面，iframe 预览 + 对话/快速操作面板 + 任务管理
- `SiteDetail.vue` (142行): 简单详情页，较少使用

**Store** (`frontend/src/stores/site.ts`): Pinia store，list/fetch/create/start/stop/delete
**API Client** (`frontend/src/api/sites.ts`): axios 封装，全部 `/sites/` 端点
**Types** (`frontend/src/types/models.ts`): Site, SiteCreateRequest, SiteUpdateRequest 接口

**导航** (`frontend/src/components/Layout/AppLayout.vue:68-72`): 侧边栏"站点管理"分组，含"我的站点"链接到 `/sites`

### 1.5 Celery + WebSocket 基础设施

- `develop_code_task` (`backend/tasks/develop_code.py`): 典型的 Celery 任务模式——获取 DB 任务 → 获取 Redis 锁 → 执行 → 释放锁
- WebSocket 推送日志模式已在 SiteEditor 中完整使用
- 克隆任务可复用此模式

### 1.6 Alembic 迁移

- 最新迁移: `20260423_0001_encrypt_api_keys.py`
- 数据库: PostgreSQL（UUID 类型、JSONB、枚举）
- 命名约定已定义在 `backend/models/base.py:12-18`

---

## 2. 需要新增/修改的内容清单

### 2.1 数据模型变更

| 变更 | 详情 |
|------|------|
| 新建 `projects` 表 | id(UUID PK), name, description, org_id(FK), owner_id(FK), deleted_at, created_at, updated_at |
| `sites` 表添加列 | `project_id` (UUID, FK → projects.id, nullable, index) |
| 数据迁移 | 每个现有 Site 自动创建同名 Project，Site.project_id 指向新 Project |

**风险点：**
- `sites` 表被 8+ 个表引用，`project_id` 设为可空 FK 不会破坏现有数据
- 数据迁移需要批量 INSERT projects + UPDATE sites，需在事务中完成
- downgrade 时需删除 projects 表及 sites.project_id 列

### 2.2 后端服务变更

| 服务 | 变更 |
|------|------|
| 新建 `ProjectService` | 项目 CRUD、仓库列表、项目下文件浏览 |
| 修改 `SiteService` | 文件路径从 `/<site_id>/` 改为 `/<project_id>/<repo_name>/`；clone 改为异步 Celery 任务 |
| 新建 Celery 任务 | `clone_repo_task`：异步克隆 + WebSocket 进度通知 |

**文件路径迁移策略：**
- D-05 决定: `generated_sites/<project_id>/<repo_name>/`
- 数据迁移时需移动现有文件: `generated_sites/<site_id>/` → `generated_sites/<project_id>/<site.name>/`
- 或者：保持现有文件不动，通过 symlink/配置映射兼容。**建议在数据迁移脚本中物理移动目录**

### 2.3 API 路由变更

| 新端点 | 说明 |
|--------|------|
| `POST /api/v2/projects` | 创建项目 |
| `GET /api/v2/projects` | 项目列表 |
| `GET /api/v2/projects/:id` | 项目详情 + 仓库列表 |
| `PUT /api/v2/projects/:id` | 更新项目 |
| `DELETE /api/v2/projects/:id` | 删除项目 |
| `POST /api/v2/projects/:id/repos` | 添加仓库（空白创建或 git clone） |
| `GET /api/v2/projects/:id/repos/:repo_id/files` | 仓库文件列表 |
| `GET /api/v2/projects/:id/repos/:repo_id/file` | 仓库文件内容 |

**兼容性：** 现有 `/api/v2/sites/` 端点需保留（SiteEditor 大量使用），但列表页逐步迁移到 projects

### 2.4 前端变更

| 文件 | 变更 |
|------|------|
| 路由 | `/sites` → `/projects`，新增 `/projects/:id`、`/projects/:id/edit` |
| 视图目录 | `Views/Sites/` → `Views/Projects/`，组件重命名 |
| AppLayout | 侧边栏"站点管理"改为"项目管理"，链接 `/projects` |
| Store | 新建 `projectStore`，管理 Project + Repo 列表 |
| API Client | 新建 `frontend/src/api/projects.ts` |
| Types | 新增 `Project`, `ProjectRepo` 类型 |
| ProjectList | 卡片显示项目名 + 仓库数 + 最后活动时间 |
| ProjectEditor | 顶部 Tab 切换仓库，下方文件树 + Monaco 编辑 |

---

## 3. 技术方案与关键决策

### 3.1 Project 模型设计

```python
class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
```

Site 表添加:
```python
project_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
)
```

### 3.2 文件存储路径迁移

**当前:** `generated_sites/<site_id>/`
**目标:** `generated_sites/<project_id>/<site_name_or_repo_name>/`

迁移策略:
1. Alembic 数据迁移创建 Project 记录并设置 `sites.project_id`
2. 文件系统迁移在 Alembic 之外单独处理（或在迁移脚本中执行 os 操作）
3. `SiteService.site_root()` 需要同时支持新旧路径（优先新路径，回退旧路径），确保平滑过渡

### 3.3 异步克隆方案

```
前端 POST /projects/:id/repos {git_url, ...}
  → 后端创建 Site 记录 (status=building)
  → 创建 AgentTask (task_type=clone_repo)
  → 启动 Celery 任务
  → 立即返回 {site_id, task_id}
  → 前端通过 WebSocket 接收克隆进度
  → 克隆完成后 site.status = stopped, 通知前端刷新
```

需要在 `TaskType` 枚举中添加 `CLONE_REPO = "clone_repo"`。

### 3.4 前端路由兼容

- `/sites` 重定向到 `/projects`
- `/sites/:id/edit` 重定向到 `/projects/:projectId/edit`（需查找 site 所属 project）
- 旧 SiteEditor 功能完整迁移到 ProjectEditor

### 3.5 Monaco 多标签页 + 多仓库

- 顶部 Tab 切换仓库，文件树跟随切换
- 编辑器标签格式: `[repo_name] path/to/file`
- 切换仓库不关闭已打开标签，但文件树只显示当前仓库

---

## 4. 风险与注意事项

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| SiteEditor 是 907 行的大组件，重构风险高 | 引入 bug、功能回退 | 分步重构：先提取逻辑到 composables，再改组件结构 |
| 文件路径迁移可能丢失数据 | 用户文件丢失 | 先 copy 再删除旧目录；提供回滚脚本 |
| Site 被 8+ 个表引用 | 修改 Site 模型影响面大 | project_id 设为可空，不破坏现有 FK |
| 克隆大仓库超时 | 用户体验差 | Celery 任务无超时限制；前端显示进度 |
| /sites/ API 仍被 SiteEditor 使用 | 不能直接删除旧 API | 保留 /sites/ 端点，新增 /projects/ 端点 |

---

## 5. 实现顺序建议

按 4 个 Plan 分步实施（与 02-CONTEXT.md Plans 对应）：

### Plan 1: 数据模型与迁移
1. 新建 `backend/models/project.py` — Project 模型
2. `backend/models/site.py` — 添加 `project_id` FK
3. `backend/models/__init__.py` — 注册 Project
4. Alembic 迁移 — DDL + 数据迁移（为每个 Site 创建 Project）
5. 验证 downgrade 可回退

### Plan 2: 仓库创建与导入
1. `backend/services/project_service.py` — Project CRUD + 仓库管理
2. 修改 `SiteService.site_root()` — 支持 project 分组路径
3. 新建 `backend/tasks/clone_repo.py` — 异步克隆 Celery 任务
4. `backend/api/v2/projects.py` — Projects + Repos API 端点
5. 注册路由到 `backend/api/__init__.py`
6. `TaskType` 枚举添加 `CLONE_REPO`

### Plan 3: 项目管理前端
1. 新建 `frontend/src/api/projects.ts`
2. 新建 `frontend/src/stores/project.ts`
3. `frontend/src/types/models.ts` — 添加 Project, ProjectRepo 类型
4. 新建 `frontend/src/views/Projects/ProjectList.vue`
5. 新建 `frontend/src/views/Projects/ProjectDetail.vue`（或 ProjectEditor）
6. 更新路由 — `/projects` 路由 + `/sites` 重定向
7. 更新 AppLayout 侧边栏导航

### Plan 4: 文件浏览与 Monaco 集成
1. 多仓库文件树组件
2. ProjectEditor 中仓库 Tab 切换
3. Monaco 多标签页（仓库前缀）
4. 文件浏览 API 接入（`/projects/:id/repos/:repo_id/files`）

---

## 6. 对后续 Phase 的影响

| Phase | 影响 |
|-------|------|
| Phase 3 (AI 编码) | PROJ-06 要求 AI 感知多仓库结构；Task 需要关联到具体 repo 而非仅 site |
| Phase 5 (Docker 部署) | 部署可能针对单个仓库或整个项目，路径逻辑需适配 |
| Phase 1 (安全加固) | Redis 锁粒度需从 site_id 扩展为 project_id + repo_id（D-11 已提及） |

---

## 7. Validation Architecture

本节定义 Phase 2 各功能区域的验证策略、测试层次和关键检查点。

### 7.1 测试基础设施现状

项目已有的测试模式（`backend/tests/`）：
- **pytest + pytest-asyncio** 异步测试框架
- **httpx.ASGITransport** 内存级 API 测试（不启动真实服务器）
- **SQLite 内存数据库** 替代 PostgreSQL 用于测试
- **tmp_path fixture** 隔离文件系统操作
- **auth_headers fixture** 复用认证流程
- **Playwright E2E**（`frontend/tests/e2e/`）仅有基础骨架（1 个冒烟测试）

Phase 2 测试应延续现有模式，不引入新测试框架。

### 7.2 按 Plan 的验证检查点

#### Plan 1: 数据模型与迁移

**单元测试 — `backend/tests/test_projects.py`**

| 测试用例 | 验证内容 |
|----------|----------|
| `test_create_project` | 创建 Project 成功，返回 name/description/org_id/owner_id |
| `test_project_has_uuid_pk` | Project.id 是有效 UUID |
| `test_site_project_id_nullable` | 无 project_id 的 Site 仍可正常创建（向后兼容） |
| `test_site_with_project_id` | Site 设置 project_id 后可正确关联到 Project |
| `test_cascade_delete_project_removes_sites` | 删除 Project 级联删除其下 Site |

**迁移验证 — 手动 + 自动化脚本**

| 检查点 | 验证方式 |
|--------|----------|
| upgrade 创建 projects 表 | `alembic upgrade head` 后检查表结构 |
| upgrade 数据迁移正确 | 每个现有 Site 有对应 Project，site.project_id 已设置 |
| downgrade 可回退 | `alembic downgrade -1` 后 projects 表被删除，sites.project_id 列被移除 |
| 升级-降级-再升级 幂等性 | 连续 upgrade→downgrade→upgrade 不报错 |
| 现有 FK 链不破坏 | 迁移后 tasks/conversations 等表查询正常 |

**风险重点验证：**
- `site_deploy_config` / `site_provider_config` 使用 `site_id`（字符串）FK 的特殊表在迁移前后均可正常操作
- 空数据库（无 Site）上执行迁移不报错
- 有 Site 但 Site 关联了 tasks/conversations 等子表数据时，迁移不破坏这些关联

#### Plan 2: 仓库创建与导入

**单元测试 — `backend/tests/test_projects.py`（扩展）**

| 测试用例 | 验证内容 |
|----------|----------|
| `test_create_blank_repo` | POST `/projects/:id/repos` 创建空白仓库，文件系统有 `.git` 目录 |
| `test_blank_repo_file_structure` | 空白仓库有预置目录结构（backend/frontend/docs） |
| `test_repo_stored_under_project_dir` | 仓库文件路径为 `generated_sites/<project_id>/<repo_name>/` |
| `test_clone_from_local_git_url` | 通过本地 git 路径克隆仓库成功（复用现有 test_create_site_from_git_repository 模式） |
| `test_clone_creates_celery_task` | 克隆请求创建了 task_type=CLONE_REPO 的 AgentTask 记录 |
| `test_clone_invalid_url_returns_error` | 无效 git URL 返回错误 |
| `test_list_repos_for_project` | GET `/projects/:id` 返回该项目下所有仓库 |
| `test_repo_files_api` | GET `/projects/:id/repos/:repo_id/files` 正确列出文件 |
| `test_repo_file_content_api` | GET `/projects/:id/repos/:repo_id/file?path=xxx` 返回文件内容 |
| `test_repo_file_path_escape_blocked` | `../` 路径穿越被拒绝（安全） |

**集成测试 — 异步克隆流程**

| 测试用例 | 验证内容 |
|----------|----------|
| `test_clone_task_execution` | Celery 任务在 eager 模式下完成克隆，Site status 从 building → stopped |
| `test_clone_task_failure_sets_error_status` | 克隆失败时 Site status 变为 error，错误信息记录在 task 中 |

**注意：** 异步克隆的完整 WebSocket 通知测试属于 E2E 范畴（见 7.3），单元测试中通过 mock 或 Celery eager 模式验证任务逻辑。

#### Plan 3: 项目管理前端

**前端无自动化单元测试框架**（项目当前没有 vitest/jest 配置），验证策略以手动 + E2E 为主：

| 检查点 | 验证方式 |
|--------|----------|
| `/projects` 路由可访问 | E2E 或手动 |
| `/sites` 重定向到 `/projects` | E2E 或手动 |
| 项目列表展示项目卡片 | 手动验证 UI |
| 创建项目对话框可用 | 手动验证 UI |
| 侧边栏"项目管理"导航正确 | 手动验证 UI |
| TypeScript 编译无报错 | `npm run build` 在 CI 中验证 |
| 项目详情页展示仓库列表 | 手动验证 UI |

#### Plan 4: 文件浏览与 Monaco 集成

| 检查点 | 验证方式 |
|--------|----------|
| 仓库 Tab 切换文件树刷新 | 手动验证 |
| 切换仓库不关闭已打开编辑器标签 | 手动验证 |
| 编辑器标签显示 `[repo_name] path` | 手动验证 |
| 多仓库文件树只显示当前仓库文件 | 手动验证 |
| 编辑文件后保存正确写入对应仓库目录 | API 测试 + 手动验证 |

### 7.3 E2E 测试（Playwright）

在 `frontend/tests/e2e/` 中新增以下测试文件：

**`project-management.spec.ts`** — 核心流程覆盖

```
1. 登录 → 导航到 /projects → 验证项目列表页渲染
2. 创建新项目 → 验证项目卡片出现在列表
3. 进入项目 → 添加空白仓库 → 验证仓库出现在 Tab 列表
4. 切换仓库 Tab → 验证文件树内容切换
5. /sites 路由 → 验证重定向到 /projects
```

**`repo-clone.spec.ts`** — 克隆流程

```
1. 登录 → 创建项目 → 通过 git URL 添加仓库
2. 验证"克隆中"加载状态显示
3. 等待克隆完成 → 验证文件树展示克隆后的文件
```

> 注意：E2E 测试依赖完整服务栈（docker compose up），仅在 CI 或手动集成测试时执行。

### 7.4 向后兼容性验证

Phase 2 的核心约束是**不破坏现有功能**。以下是专门的兼容性验证清单：

| 验证项 | 具体方法 |
|--------|----------|
| 现有 `/api/v2/sites/` 端点全部正常 | 运行现有 `test_sites.py` 全部用例，确保 PASS |
| 现有 SiteEditor 功能不回退 | 手动在 /projects/:id/edit 中重复 SiteEditor 的核心操作 |
| 数据迁移后旧数据可访问 | 在有真实数据的环境上执行迁移，验证旧 Site 可通过 Project 访问 |
| 文件路径迁移后旧文件可读 | `SiteService.site_root()` 的兼容逻辑测试 |
| 已有 tasks/conversations 不受影响 | 迁移后查询 tasks/conversations 表验证数据完整 |

### 7.5 高风险区域与额外验证

| 风险区域 | 原因 | 额外验证措施 |
|----------|------|-------------|
| **Alembic 数据迁移** | 在生产数据上执行 DDL + DML，错误不可逆 | 在 staging 环境先执行；准备 SQL 回滚脚本；执行前 pg_dump 备份 |
| **文件系统路径迁移** | 物理移动目录可能丢失数据 | 使用 copy → verify → delete 策略；迁移脚本打印详细日志；提供 dry-run 模式 |
| **SiteEditor 重构为 ProjectEditor** | 907 行大组件重构，功能回退风险最高 | 按 composable 拆分后逐步重构；每步后手动验证核心流程（文件编辑、对话、任务管理） |
| **SiteService.site_root() 路径变更** | 影响所有使用文件路径的功能（编辑、部署、AI 编码） | 新旧路径兼容逻辑 + 单元测试覆盖两种路径场景 |
| **Celery 异步克隆** | 新增任务类型，失败处理和状态更新逻辑 | Celery eager 模式单元测试 + 真实 Redis 集成测试 |

### 7.6 验证执行顺序

```
Plan 1 完成后：
  ✓ 运行 pytest backend/tests/ — 全部用例 PASS（含新增 project 测试）
  ✓ 执行 alembic upgrade/downgrade 循环验证
  ✓ 确认现有 test_sites.py 全部 PASS（向后兼容）

Plan 2 完成后：
  ✓ 运行 pytest backend/tests/ — 含仓库创建/克隆/文件浏览测试
  ✓ 手动验证 Celery 克隆任务（docker compose 环境）
  ✓ 确认现有 test_sites.py 全部 PASS

Plan 3 完成后：
  ✓ npm run build 编译通过（TypeScript 无报错）
  ✓ 手动验证项目列表、创建、路由重定向
  ✓ 确认现有 test_sites.py 全部 PASS

Plan 4 完成后：
  ✓ npm run build 编译通过
  ✓ 手动验证多仓库 Tab 切换、文件树、Monaco 标签页
  ✓ 运行 Playwright E2E 测试
  ✓ 全量回归：所有后端测试 + 前端构建 + 手动 SiteEditor 功能验证
```

### 7.7 CI 集成建议

当前项目无 CI 配置，建议在 Phase 2 期间至少保证以下命令在开发流程中运行：

```bash
# 后端测试
cd backend && python -m pytest tests/ -v

# 前端构建检查
cd frontend && npm run build

# Alembic 迁移检查（需数据库连接）
cd backend && alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

---

*Research completed: 2026-04-23*
*Updated: 2026-04-23 — added Validation Architecture (Section 7)*
*Phase: 02-multi-repo-project-model*
