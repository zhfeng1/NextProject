# Phase 2: 多仓库项目模型 - Context

**Gathered:** 2026-04-23
**Status:** Ready for planning

<domain>
## Phase Boundary

用户可以创建项目并关联多个 git 仓库，支持微服务和前后端分离架构。覆盖需求：PROJ-01, PROJ-02, PROJ-03, PROJ-04, PROJ-05。

</domain>

<decisions>
## Implementation Decisions

### Project 与 Site 关系
- **D-01:** Site 成为 Project 下的子级概念，每个 Site 对应一个仓库。Project 是新的顶层实体
- **D-02:** 现有 Site 数据通过 Alembic 数据迁移自动转换为单仓库项目——每个 Site 自动创建同名 Project，Site 归入其下。用户无感
- **D-03:** 前端完全用"项目"替换"站点"概念。SiteList/SiteDetail/SiteEditor 页面重构为 ProjectList/ProjectDetail/ProjectEditor
- **D-04:** 数据库层面：新建 Project 表（name, description, org_id, owner_id），Site 表添加可空 project_id FK 关联到 Project

### 仓库存储与导入
- **D-05:** 多仓库文件存储按项目分组：`generated_sites/<project_id>/<repo_name>/`，每个仓库是独立 git 目录
- **D-06:** 支持私有仓库导入——HTTPS + token 和 SSH 两种认证方式。用户可在导入时提供 Personal Access Token 或配置 SSH Key
- **D-07:** 克隆过程异步执行（Celery 任务）+ WebSocket 进度通知。前端显示"克隆中..."加载状态，克隆完成后通知刷新

### 前端项目视图
- **D-08:** 项目列表页采用卡片网格布局，沿用现有 SiteList 卡片风格，展示项目名称、仓库数、最后活动时间
- **D-09:** 项目详情页使用顶部 Tab 切换仓库，下方显示当前仓库内容（文件浏览/编辑器）
- **D-10:** 前端路由和视图目录完全重命名：`/sites` → `/projects`，`Views/Sites/` → `Views/Projects/`

### Monaco 文件编辑集成
- **D-11:** 文件树一次只展示当前 Tab 选中仓库的文件，切换 Tab 即切换文件树
- **D-12:** Monaco 编辑器支持多标签页打开文件，标签页显示仓库前缀区分来源（如 `[frontend] src/main.ts`）。切换仓库不关闭已打开的标签

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 数据模型
- `backend/models/site.py` — 现有 Site 模型，需添加 project_id FK，新建 Project 模型
- `backend/models/base.py` — Base 类和 ORM 基础
- `backend/models/mixins.py` — UUIDPrimaryKeyMixin, TimestampMixin 混入

### 后端服务
- `backend/services/site_service.py` — 站点生命周期管理、git 操作、文件浏览。需扩展为项目+多仓库管理
- `backend/services/task_service.py` — 任务创建和执行，克隆任务的集成点

### API 路由
- `backend/api/v2/sites.py` — 站点 CRUD 端点，需重构为项目+仓库端点
- `backend/api/__init__.py` — 路由注册，需添加 projects 路由

### 数据库迁移
- `backend/alembic/versions/` — 迁移文件目录，新建 Project 表 + Site 添加 project_id

### 前端视图
- `frontend/src/views/Sites/SiteList.vue` — 现有站点列表，重构为 ProjectList
- `frontend/src/views/Sites/SiteDetail.vue` — 现有站点详情，重构为 ProjectDetail
- `frontend/src/views/Sites/SiteEditor.vue` — 现有站点编辑器，重构为 ProjectEditor + 多仓库 Tab
- `frontend/src/router/index.ts` — 路由配置，/sites → /projects
- `frontend/src/api/sites.ts` — 站点 API 客户端，需重构为 projects API

### Phase 1 相关
- `.planning/phases/01-security-hardening/01-CONTEXT.md` — Phase 1 决策，D-11 Redis 锁按 site_id/repo_id 粒度

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Site` 模型（`backend/models/site.py`）: 已有完整的 CRUD 字段，可直接复用为仓库实体
- `SiteService`（`backend/services/site_service.py`）: git 初始化、文件浏览、进程管理能力可复用
- `SiteList.vue` 卡片布局: 可作为 ProjectList 的基础重构
- `SiteEditor.vue` Monaco 集成: 文件树和编辑器逻辑可扩展支持多仓库
- Celery + WebSocket: 异步任务和实时通知基础设施已就绪（用于克隆任务）
- `UUIDPrimaryKeyMixin` + `TimestampMixin`: 新 Project 模型可直接使用

### Established Patterns
- Service singleton 模式: `site_service`, `task_service` 等
- HTTPException 统一错误处理
- `{"ok": True/False, ...}` JSON 响应格式
- Alembic 数据迁移 + data migration（Phase 1 已有先例）
- `<script setup lang="ts">` Vue 组件风格
- `@/` 路径别名

### Integration Points
- `backend/api/__init__.py` — 注册新的 projects 路由
- `frontend/src/router/index.ts` — 添加 /projects 路由
- `docker-compose.yml` — 如需调整 generated_sites 挂载路径
- `frontend/src/components/Layout/AppLayout.vue` — 侧边栏导航从"站点"改为"项目"

</code_context>

<specifics>
## Specific Ideas

- 数据迁移策略与 Phase 1 相同（Alembic data migration），每个现有 Site 自动创建同名 Project 并关联
- 克隆任务复用现有 Celery + WebSocket 推送模式，参考 `develop_code` 任务
- Monaco 标签页仓库前缀格式：`[repo_name] path/to/file`，便于区分来源
- Tab 切换仓库时文件树刷新，但已打开的编辑器标签保持不变

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-multi-repo-project-model*
*Context gathered: 2026-04-23*
