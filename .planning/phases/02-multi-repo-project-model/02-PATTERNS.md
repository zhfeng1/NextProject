# Phase 2: 多仓库项目模型 — Patterns

**Date:** 2026-04-23
**Phase:** 02-multi-repo-project-model

---

## 1. 文件清单与角色分类

### 1.1 后端 — 数据模型层 (Model)

| 文件 | 操作 | 角色 | 最近类似物 |
|------|------|------|-----------|
| `backend/models/project.py` | **新建** | Model — 新实体 | `backend/models/site.py` |
| `backend/models/site.py` | **修改** | Model — 添加 FK | 自身 |
| `backend/models/enums.py` | **修改** | Enum — 新增 TaskType | 自身 |
| `backend/models/__init__.py` | **修改** | 注册 — 导出新模型 | 自身 |

### 1.2 后端 — 数据迁移 (Migration)

| 文件 | 操作 | 角色 | 最近类似物 |
|------|------|------|-----------|
| `backend/alembic/versions/20260423_0002_add_projects.py` | **新建** | DDL + 数据迁移 | `20260331_0001_phase_2_features.py`（DDL）+ `20260423_0001_encrypt_api_keys.py`（数据迁移） |

### 1.3 后端 — 服务层 (Service)

| 文件 | 操作 | 角色 | 最近类似物 |
|------|------|------|-----------|
| `backend/services/project_service.py` | **新建** | Service — CRUD + 仓库管理 | `backend/services/site_service.py` |
| `backend/services/site_service.py` | **修改** | Service — 路径迁移 + clone 解耦 | 自身 |

### 1.4 后端 — Celery 任务 (Task)

| 文件 | 操作 | 角色 | 最近类似物 |
|------|------|------|-----------|
| `backend/tasks/clone_repo.py` | **新建** | Celery 任务 | `backend/tasks/develop_code.py` |

### 1.5 后端 — API 路由 (Router)

| 文件 | 操作 | 角色 | 最近类似物 |
|------|------|------|-----------|
| `backend/api/v2/projects.py` | **新建** | Router — Projects + Repos 端点 | `backend/api/v2/sites.py` |
| `backend/api/__init__.py` | **修改** | 路由注册 | 自身 |

### 1.6 前端 — 类型 (Types)

| 文件 | 操作 | 角色 | 最近类似物 |
|------|------|------|-----------|
| `frontend/src/types/models.ts` | **修改** | Types — 新增 Project/ProjectRepo | 自身（Site 接口） |

### 1.7 前端 — API Client

| 文件 | 操作 | 角色 | 最近类似物 |
|------|------|------|-----------|
| `frontend/src/api/projects.ts` | **新建** | API Client | `frontend/src/api/sites.ts` |

### 1.8 前端 — Store

| 文件 | 操作 | 角色 | 最近类似物 |
|------|------|------|-----------|
| `frontend/src/stores/project.ts` | **新建** | Pinia Store | `frontend/src/stores/site.ts` |

### 1.9 前端 — 视图 (Views)

| 文件 | 操作 | 角色 | 最近类似物 |
|------|------|------|-----------|
| `frontend/src/views/Projects/ProjectList.vue` | **新建** | 页面 — 项目列表 | `frontend/src/views/Sites/SiteList.vue` |
| `frontend/src/views/Projects/ProjectDetail.vue` | **新建** | 页面 — 项目详情 | `frontend/src/views/Sites/SiteDetail.vue` |
| `frontend/src/views/Projects/ProjectEditor.vue` | **新建** | 页面 — 项目编辑器 + 多仓库 | `frontend/src/views/Sites/SiteEditor.vue` |

### 1.10 前端 — 路由与布局

| 文件 | 操作 | 角色 | 最近类似物 |
|------|------|------|-----------|
| `frontend/src/router/index.ts` | **修改** | 路由配置 | 自身 |
| `frontend/src/components/Layout/AppLayout.vue` | **修改** | 侧边栏导航 | 自身 |

---

## 2. 数据流向

```
[用户] → [前端 ProjectList/ProjectEditor]
        → [API Client: projects.ts]
        → [Router: /api/v2/projects]
        → [Service: project_service]
        → [Model: Project / Site]
        → [DB: projects 表 + sites 表]
        → [文件系统: generated_sites/<project_id>/<repo_name>/]

[克隆流程]
  → POST /projects/:id/repos {git_url}
  → project_service → 创建 Site(status=building) + AgentTask
  → Celery: clone_repo_task
  → SiteService.clone_site_repository()
  → WebSocket 进度通知 → 前端刷新
```

---

## 3. 逐文件模式提取

### 3.1 `backend/models/project.py` — 新建

**类似物:** `backend/models/site.py:19-33`

```python
# ---- 来源: backend/models/site.py:1-9, 19-33 ----
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

class Site(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sites"
    site_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
```

**应用规则:**
- 继承 `UUIDPrimaryKeyMixin, TimestampMixin, Base`（与 Site 完全一致）
- 字段: `name`(String 255), `description`(Text, default=""), `org_id`(FK→organizations), `owner_id`(FK→users), `deleted_at`
- 注意: `UUIDPrimaryKeyMixin` 在 `base.py:36-37` 定义用 `UUID(as_uuid=True)`，但 `mixins.py:8-9` 定义用 `String(36)`。Site 模型 import 自 `base.py`，Project 应与 Site 保持一致也 import 自 `base.py`

---

### 3.2 `backend/models/site.py` — 修改

**当前代码:** `backend/models/site.py:19-33`

```python
# ---- 来源: backend/models/site.py:19-33 ----
class Site(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sites"
    site_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    # ... 其他字段 ...
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
```

**应用规则:**
- 添加 `project_id` 可空 FK，紧跟在 `owner_id` 之后：
  ```python
  project_id: Mapped[str | None] = mapped_column(
      ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True, default=None
  )
  ```
- `nullable=True` 确保向后兼容：已有 Site 数据不受影响
- 需要在文件顶部确保 `from backend.models.project import Project` 不形成循环导入（FK 用字符串 `"projects.id"` 避免循环）

---

### 3.3 `backend/models/enums.py` — 修改

**当前代码:** `backend/models/enums.py:21-26`

```python
# ---- 来源: backend/models/enums.py:21-26 ----
class TaskType(str, enum.Enum):
    DEVELOP_CODE = "develop_code"
    TEST_LOCAL_PLAYWRIGHT = "test_local_playwright"
    DEPLOY_LOCAL = "deploy_local"
    DEPLOY_APOLLO = "deploy_apollo"
```

**应用规则:**
- 添加 `CLONE_REPO = "clone_repo"`

---

### 3.4 `backend/models/__init__.py` — 修改

**当前代码:** `backend/models/__init__.py:1-51`

```python
# ---- 来源: backend/models/__init__.py:1-6 ----
from backend.models.base import Base
from backend.models.enums import PlanTier, SiteStatus, TaskType, UserRole
from backend.models.app_config import AppConfig
from backend.models.mcp_service import UserMcpService
from backend.models.organization import Organization, OrganizationMember
from backend.models.site import Site, SiteDeployConfig, SiteProviderConfig
```

**应用规则:**
- 添加 `from backend.models.project import Project`
- 在 `__all__` 列表中添加 `"Project"`

---

### 3.5 `backend/alembic/versions/20260423_0002_add_projects.py` — 新建

**DDL 类似物:** `backend/alembic/versions/20260331_0001_phase_2_features.py`

```python
# ---- 来源: 20260331_0001_phase_2_features.py:29-43 (create_table 模式) ----
op.create_table(
    'site_requirement_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('site_id', sa.String(length=36), nullable=False),
    # ...
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
)
op.create_index(op.f('ix_...'), '...', ['...'], unique=False)
```

**数据迁移类似物:** `backend/alembic/versions/20260423_0001_encrypt_api_keys.py:27-41`

```python
# ---- 来源: 20260423_0001_encrypt_api_keys.py:27-41 (bind + sa.text 模式) ----
def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, api_key FROM user_llm_providers WHERE api_key IS NOT NULL AND api_key != ''")
    )
    for row in rows:
        # ... process row ...
        bind.execute(
            sa.text("UPDATE user_llm_providers SET api_key = :key WHERE id = :id"),
            {"key": encrypted, "id": row[0]},
        )
```

**应用规则:**
- `revision`: `"20260423_0002"`，`down_revision`: `"20260423_0001"`
- upgrade 分两步：
  1. DDL：`op.create_table('projects', ...)` + `op.add_column('sites', sa.Column('project_id', ...))`
  2. 数据迁移：为每个 Site 创建 Project（INSERT），然后 UPDATE `sites.project_id`
- downgrade：`op.drop_column('sites', 'project_id')` + `op.drop_table('projects')`
- 列类型用 `sa.String(length=36)` 保持与现有表一致

---

### 3.6 `backend/services/project_service.py` — 新建

**类似物:** `backend/services/site_service.py`（单例 + CRUD 模式）

```python
# ---- 来源: backend/services/site_service.py:122-124 (单例声明) ----
class SiteService:
    def site_root(self, site_id: str) -> Path:
        return GENERATED_SITES_ROOT / site_id

# ---- 来源: backend/services/site_service.py:571 ----
site_service = SiteService()
```

**CRUD 查询模式:**
```python
# ---- 来源: backend/services/site_service.py:415-425 (list 查询) ----
async def list_sites(self, db: AsyncSession, user: object, include_deleted: bool = False) -> list[Site]:
    query = select(Site)
    user_id = getattr(user, "id", None)
    org_id = getattr(user, "default_org_id", None)
    if user_id is not None and hasattr(Site, "owner_id"):
        query = query.where(or_(Site.owner_id == user_id, Site.org_id == org_id))
    if not include_deleted and hasattr(Site, "deleted_at"):
        query = query.where(Site.deleted_at.is_(None))
    query = query.order_by(Site.created_at.asc())
    rows = await db.execute(query)
    return list(rows.scalars().all())
```

**创建模式:**
```python
# ---- 来源: backend/services/site_service.py:469-479 (创建实体) ----
site = Site(
    id=str(uuid.uuid4()),
    site_id=sid,
    name=(name or sid).strip() or sid,
    owner_id=getattr(current_user, "id", None),
    org_id=getattr(current_user, "default_org_id", None),
    status=SiteStatus.STOPPED.value,
    # ...
)
db.add(site)
await db.flush()
```

**序列化模式:**
```python
# ---- 来源: backend/services/site_service.py:398-413 ----
def serialize_site(self, site: Site) -> dict[str, Any]:
    return {
        "id": str(site.id),
        "site_id": site.site_id,
        "name": site.name,
        "status": ...,
        "created_at": getattr(site, "created_at", None).isoformat() if getattr(site, "created_at", None) else None,
    }
```

**应用规则:**
- `class ProjectService` + 底部 `project_service = ProjectService()`
- `list_projects(db, user)` — 按 `or_(owner_id, org_id)` 过滤 + `deleted_at IS NULL`
- `create_project(db, current_user, name, description)` — `id=str(uuid.uuid4())`
- `get_project(db, project_id, current_user)` — 与 `get_site_by_public_id` 类似的权限检查模式
- `serialize_project(project)` — 返回 `{"ok": True, ...}` 嵌套数据
- `add_repo_to_project(db, project_id, ...)` — 创建 Site + 关联 project_id

---

### 3.7 `backend/services/site_service.py` — 修改

**需要变更的方法:**

```python
# ---- 来源: backend/services/site_service.py:123-124 ----
def site_root(self, site_id: str) -> Path:
    return GENERATED_SITES_ROOT / site_id
```

**应用规则:**
- `site_root()` 改为支持 project 分组路径：优先 `generated_sites/<project_id>/<repo_name>/`，回退 `generated_sites/<site_id>/`
- 可能需要新增 `site_root_by_project(project_id, repo_name)` 方法，或修改 `site_root` 签名
- `clone_site_repository()` 保持不动（被 Celery 任务调用），但从 `create_site()` 中移除同步调用

---

### 3.8 `backend/tasks/clone_repo.py` — 新建

**类似物:** `backend/tasks/develop_code.py:1-32`

```python
# ---- 来源: backend/tasks/develop_code.py:1-32 (完整文件) ----
from __future__ import annotations
import asyncio
from backend.core.celery_app import celery_app
from backend.core.redis_lock import acquire_site_lock, release_site_lock
from backend.models import Task
from backend.services.task_service import task_service
from backend.tasks._helpers import task_db_session

@celery_app.task(bind=True, max_retries=60, default_retry_delay=30)
def develop_code_task(self, task_id: str) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        async with task_db_session() as db:
            task = await db.get(Task, task_id)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            site_id = str(task.site_id)
        if not acquire_site_lock(site_id, task_id):
            raise self.retry(countdown=30)
        try:
            async with task_db_session() as db:
                result_task = await task_service.run_develop_task(db, task_id)
                return task_service.serialize_task(result_task)
        finally:
            release_site_lock(site_id, task_id)
    return asyncio.run(_run())
```

**应用规则:**
- 同样的 `@celery_app.task(bind=True, ...)` + `asyncio.run()` 模式
- 获取 Redis 锁（site 级别）
- 内部调用 `site_service.clone_site_repository()` 而非 `task_service.run_develop_task()`
- 完成后更新 Site.status → `stopped`；失败时 → `error`
- 通过 WebSocket 推送进度（复用 `task_service.append_log` + `task_service.update_status`）

---

### 3.9 `backend/api/v2/projects.py` — 新建

**类似物:** `backend/api/v2/sites.py:1-161`

```python
# ---- 来源: backend/api/v2/sites.py:1-13 (路由声明 + 依赖注入) ----
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from backend.api.deps import get_current_user, get_db, require_role
from backend.services.site_service import site_service
router = APIRouter(prefix="/sites")
```

**CRUD 端点模式:**
```python
# ---- 来源: backend/api/v2/sites.py:16-23 (列表) ----
@router.get("")
async def list_sites(
    include_deleted: bool = Query(default=False),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    sites = await site_service.list_sites(db, user=current_user, include_deleted=include_deleted)
    return {"ok": True, "sites": [site_service.serialize_site(site) for site in sites]}

# ---- 来源: backend/api/v2/sites.py:26-46 (创建) ----
@router.post("")
async def create_site(
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.create_site(db, current_user=current_user, ...)
    return {"ok": True, "site": site_service.serialize_site(site)}

# ---- 来源: backend/api/v2/sites.py:153-160 (删除) ----
@router.delete("/{site_id}")
async def delete_site(
    site_id: str,
    current_user: object = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await site_service.delete_site(db, site_id, current_user)
    return {"ok": True}
```

**文件浏览端点模式:**
```python
# ---- 来源: backend/api/v2/sites.py:96-116 (文件列表/内容) ----
@router.get("/{site_id}/files")
async def list_site_files(
    site_id: str,
    path: str = Query(default=""),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    site = await site_service.get_site_by_public_id(db, site_id, current_user)
    data = site_service.list_site_files(site.site_id, path)
    return {"ok": True, **data}
```

**应用规则:**
- `router = APIRouter(prefix="/projects")`
- 端点: `GET /`, `POST /`, `GET /{id}`, `PUT /{id}`, `DELETE /{id}`
- 仓库端点: `POST /{id}/repos`, `GET /{id}/repos/{repo_id}/files`, `GET /{id}/repos/{repo_id}/file`
- 统一使用 `{"ok": True/False, ...}` 响应格式
- 依赖注入: `Depends(get_current_user)`, `Depends(get_db)`

---

### 3.10 `backend/api/__init__.py` — 修改

**当前注册模式:** `backend/api/__init__.py:5-6, 14`

```python
# ---- 来源: backend/api/__init__.py:5-6 ----
from backend.api.v2 import auth, conversations, deploy, mcp, providers, sites, skills, stats, tasks, templates, versions, websocket, workflows

# ---- 来源: backend/api/__init__.py:14 ----
router.include_router(sites.router, prefix="/api/v2", tags=["Sites"])
```

**应用规则:**
- import 添加 `projects`
- 添加 `router.include_router(projects.router, prefix="/api/v2", tags=["Projects"])`

---

### 3.11 `frontend/src/types/models.ts` — 修改

**当前 Site 类型:** `frontend/src/types/models.ts:24-33`

```typescript
// ---- 来源: frontend/src/types/models.ts:24-33 ----
export interface Site {
  site_id: string
  name: string
  status: 'running' | 'stopped' | 'failed' | 'building'
  port?: number
  preview_url?: string
  internal_url?: string
  config?: Record<string, unknown>
  created_at: string
}
```

**应用规则:**
- 新增 `Project` 接口（id, name, description, repo_count, last_activity, created_at）
- 新增 `ProjectRepo` 接口（复用 Site 字段子集 + repo_name）
- Site 接口添加可选 `project_id?: string`

---

### 3.12 `frontend/src/api/projects.ts` — 新建

**类似物:** `frontend/src/api/sites.ts:1-72`

```typescript
// ---- 来源: frontend/src/api/sites.ts:1-18 ----
import client from './client'
import type { Site, SiteCreateRequest, SiteUpdateRequest } from '@/types/models'

export const sitesAPI = {
  list() {
    return client.get<any, { ok: boolean; sites: Site[] }>('/sites')
  },
  create(data: SiteCreateRequest) {
    return client.post<any, { ok: boolean; site: Site }>('/sites', data)
  },
  get(siteId: string) {
    return client.get<any, { ok: boolean; site: Site }>(`/sites/${siteId}`)
  },
}
```

**应用规则:**
- `export const projectsAPI = { ... }`
- 端点前缀 `/projects`
- 方法: `list`, `create`, `get`, `update`, `delete`, `addRepo`, `listRepoFiles`, `getRepoFile`
- 返回类型使用新的 `Project` / `ProjectRepo` 类型

---

### 3.13 `frontend/src/stores/project.ts` — 新建

**类似物:** `frontend/src/stores/site.ts:1-85`

```typescript
// ---- 来源: frontend/src/stores/site.ts:1-16, 22-31 ----
import { defineStore } from 'pinia'
import { sitesAPI } from '@/api/sites'
import type { Site } from '@/types/models'

interface SiteState {
  sites: Site[]
  currentSite: Site | null
  loading: boolean
}

export const useSiteStore = defineStore('site', {
  state: (): SiteState => ({
    sites: [],
    currentSite: null,
    loading: false,
  }),
  actions: {
    async fetchSites() {
      this.loading = true
      try {
        const response = await sitesAPI.list()
        this.sites = response.sites
      } finally {
        this.loading = false
      }
    },
  },
})
```

**应用规则:**
- `defineStore('project', { ... })`
- State: `projects`, `currentProject`, `currentProjectRepos`, `loading`
- Actions: `fetchProjects`, `fetchProject`, `createProject`, `deleteProject`, `addRepo`

---

### 3.14 `frontend/src/views/Projects/ProjectList.vue` — 新建

**类似物:** `frontend/src/views/Sites/SiteList.vue:1-294`

```vue
<!-- ---- 来源: SiteList.vue:1-10 (script setup 头部) ---- -->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSiteStore } from '@/stores/site'
import { formatDate } from '@/utils/format'
import type { Site } from '@/types/models'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card'
```

```vue
<!-- ---- 来源: SiteList.vue:142-153 (卡片网格模板) ---- -->
<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
  <Card v-for="site in filteredSites" :key="site.site_id" class="flex flex-col">
    <CardHeader class="flex flex-row items-center justify-between space-y-0">
      <CardTitle class="text-lg font-bold flex items-center gap-2">
        <Globe class="w-5 h-5 text-muted-foreground" />
        {{ site.name }}
      </CardTitle>
    </CardHeader>
    <CardContent class="flex-1 text-sm text-muted-foreground space-y-2">
      <!-- ... -->
    </CardContent>
  </Card>
</div>
```

**应用规则:**
- 用 `useProjectStore()` 替换 `useSiteStore()`
- 卡片显示: 项目名 + 仓库数 + 最后活动时间（D-08）
- 创建对话框简化为项目名 + 描述（仓库在项目详情页添加）
- 路由跳转到 `/projects/:id/edit`

---

### 3.15 `frontend/src/views/Projects/ProjectEditor.vue` — 新建

**类似物:** `frontend/src/views/Sites/SiteEditor.vue`（907 行，按 composable 拆分）

**核心新增模式（D-09, D-11, D-12）:**
- 顶部 Tab 列表切换仓库（`<Tabs>` 组件）
- 文件树跟随 Tab 切换，只展示当前仓库文件
- Monaco 编辑器标签格式: `[repo_name] path/to/file`
- 切换仓库不关闭已打开标签

---

### 3.16 `frontend/src/router/index.ts` — 修改

**当前路由:** `frontend/src/router/index.ts:37-57`

```typescript
// ---- 来源: frontend/src/router/index.ts:43-57 ----
{
  path: 'sites',
  name: 'SiteList',
  component: () => import('@/views/Sites/SiteList.vue'),
},
{
  path: 'sites/:id',
  name: 'SiteDetail',
  component: () => import('@/views/Sites/SiteDetail.vue'),
},
{
  path: 'sites/:id/edit',
  name: 'SiteEditor',
  component: () => import('@/views/Sites/SiteEditor.vue'),
},
```

**应用规则:**
- 新增 `/projects` 路由组:
  ```typescript
  { path: 'projects', name: 'ProjectList', component: () => import('@/views/Projects/ProjectList.vue') },
  { path: 'projects/:id', name: 'ProjectDetail', component: () => import('@/views/Projects/ProjectDetail.vue') },
  { path: 'projects/:id/edit', name: 'ProjectEditor', component: () => import('@/views/Projects/ProjectEditor.vue') },
  ```
- `/sites` 重定向到 `/projects`
- 保留 `/sites/:id/edit` 路由（SiteEditor 仍在使用中，兼容期内保留）

---

### 3.17 `frontend/src/components/Layout/AppLayout.vue` — 修改

**当前侧边栏:** `frontend/src/components/Layout/AppLayout.vue:67-96`

```vue
<!-- ---- 来源: AppLayout.vue:67-74 ---- -->
<SidebarGroup>
  <SidebarGroupLabel>站点管理</SidebarGroupLabel>
  <SidebarGroupContent>
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton as-child :isActive="route.path === '/sites'">
          <router-link to="/sites">
            <Globe class="w-4 h-4 mr-2" />
            <span>我的站点</span>
          </router-link>
        </SidebarMenuButton>
      </SidebarMenuItem>
```

**应用规则:**
- `SidebarGroupLabel` 从 "站点管理" 改为 "项目管理"
- 第一个菜单项从 "我的站点" `/sites` 改为 "我的项目" `/projects`
- `isActive` 判断改为 `route.path.startsWith('/projects')`

---

## 4. 任务入队模式（Celery 调度集成点）

新 `clone_repo_task` 需要注册到 `TaskService.enqueue_task()`。

**当前入队模式:** `backend/services/task_service.py:315-330`

```python
# ---- 来源: backend/services/task_service.py:315-330 ----
def enqueue_task(self, task: Task) -> None:
    try:
        if task.task_type == "develop_code":
            from backend.tasks.develop_code import develop_code_task
            develop_code_task.delay(str(task.id))
        elif task.task_type in {"deploy_local", "deploy_apollo"}:
            from backend.tasks.deploy import deploy_task
            deploy_task.delay(str(task.id))
        elif task.task_type == "test_local_playwright":
            from backend.tasks.test import smoke_test_task
            smoke_test_task.delay(str(task.id))
    except Exception:
        return
```

**应用规则:**
- 添加 `elif task.task_type == "clone_repo":` 分支
- `from backend.tasks.clone_repo import clone_repo_task`
- `clone_repo_task.delay(str(task.id))`
- 同时在 `SUPPORTED_TASK_TYPES` 集合中添加 `"clone_repo"`

---

## 5. 关键约束总结

| 约束 | 来源 | 影响 |
|------|------|------|
| `project_id` 必须 nullable | D-04, 向后兼容 | Site 模型修改、迁移脚本 |
| `{"ok": True/False}` JSON 响应 | 现有模式 | 所有新 API 端点 |
| Service 单例 `xxx_service = XxxService()` | 现有模式 | ProjectService |
| `UUIDPrimaryKeyMixin + TimestampMixin + Base` | 现有模式 | Project 模型 |
| `str(uuid.uuid4())` 作为 PK | 现有模式（site_service.py:470） | Project 创建 |
| `@celery_app.task(bind=True) + asyncio.run()` | develop_code.py | clone_repo_task |
| `<script setup lang="ts">` | 现有前端模式 | 所有新 Vue 组件 |
| shadcn-vue 组件（Button, Card, Dialog...） | SiteList.vue | ProjectList/Editor |
| Pinia `defineStore` + `state/getters/actions` | site.ts store | project.ts store |
| `client.get/post` + `@/types/models` 类型 | sites.ts API | projects.ts API |

---

*Patterns extracted: 2026-04-23*
*Phase: 02-multi-repo-project-model*
