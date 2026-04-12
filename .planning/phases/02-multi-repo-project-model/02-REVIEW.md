# Phase 02 代码审查报告：多仓库项目模型

**审查日期**: 2026-04-23  
**审查范围**: 后端 API/服务层 + 前端视图/Store/类型  
**审查深度**: Standard

---

## 一、总体评估

多仓库项目模型（Project → Site/Repo 一对多）已基本落地，核心功能链路可以跑通：项目 CRUD、仓库添加（空白/Git clone）、文件树浏览、文件内容只读查看。前后端接口契约对齐，类型定义完整，安全防护有若干已知问题的修复标注。但仍存在以下几类问题需要关注。

---

## 二、后端审查

### 2.1 `backend/models/project.py` & `backend/models/site.py`

**正常点**
- `Project` 与 `Site` 通过 `project_id FK(ondelete=CASCADE)` 关联，数据层级清晰。
- `Site.port` 字段保留 `unique=True`，但对无端口的 repo 来说会是 `NULL`，SQLite 允许多行 NULL unique，无冲突。

**问题**
- `Project` 缺少 `repos` 反向关系（`relationship`），查询 `get_project_repos` 只能通过额外查询完成，增加了 N+1 风险（见 2.2）。
- `Site.root_path`、`Site.preview_url`、`Site.internal_url` 字段已在数据库定义，但 `project_service.add_repo` 创建 site 时**未写入** `root_path`，依赖运行时路径推算，存在不一致风险。

### 2.2 `backend/services/project_service.py`

**正常点**
- `validate_repo_name` 正则防止路径穿越名称（ISSUE-04）。
- `add_repo` 对带 Git URL 的仓库使用 Celery 异步克隆任务，正确加密 `git_password`（ISSUE-03）。
- `delete_project` 软删除同步软删子仓库。

**问题**

| 编号 | 位置 | 描述 |
|------|------|------|
| R-01 | `list_projects` | 遍历每个项目分别查询 repos（`get_project_repos`），形成 **N+1 查询**；项目多时性能差 |
| R-02 | `serialize_project` | `repo_count` 依赖传入 `repos` 列表长度，但 `list_projects` 路径每个项目都做了完整查询后传入，逻辑冗余 |
| R-03 | `add_repo` | 空白 repo 同步调用 `site_service.ensure_site_structure()`，该方法内部会运行 `git init/add/commit` 三个 subprocess，在 API 请求路径中阻塞，高延迟 |
| R-04 | `get_project` | 权限验证同时检查 `owner_id` 和 `org_id`，但超级管理员路径未处理（`is_superuser` 未考虑），与 `site_service.get_site_by_public_id` 行为不一致 |
| R-05 | `delete_project` | 只软删 db 记录，没有清理磁盘上的 `project_root` 目录，磁盘泄漏 |

### 2.3 `backend/api/v2/projects.py`

**正常点**
- `list_repo_files` / `get_repo_file` 校验 `site.project_id == project_id`（NEW-03），防跨项目访问。
- 所有路由依赖 `get_current_user` 认证保护。

**问题**

| 编号 | 位置 | 描述 |
|------|------|------|
| R-06 | `list_projects`（第 23 行） | 对每个 project 调用 `get_project_repos`，与 R-01 同源 N+1 |
| R-07 | `add_repo`（第 86-97 行） | `repo_name` 非法时返回 `{"ok": False, "error": ...}`（HTTP 200），但实际 `validate_repo_name` 会抛 `HTTPException(400)`；文档/测试期望 400，实际路径正确，但注释中的早期返回逻辑已成死代码 |
| R-08 | `get_repo_file` / `list_repo_files` | `project` 变量查询后未使用（第 108、127 行），只用于权限检查，可改为更简洁的 `await project_service.get_project(...)` 独立校验，但整体没有功能错误 |

### 2.4 `backend/services/site_service.py`

**正常点**
- `list_site_files` 过滤 `.git` 目录，防止泄露 git 元数据。
- `resolve_site_path` 用 `relative_to` 防止路径穿越（ISSUE-07）。
- `clone_site_repository` 支持 `override_root`，供 project repo 使用。

**问题**

| 编号 | 位置 | 描述 |
|------|------|------|
| R-09 | `serialize_site`（第 399 行） | 序列化中不包含 `project_id` 字段，但前端 `Site` 类型声明了 `project_id?: string`；前端拿不到该字段 |
| R-10 | `ensure_site_structure` | 同 R-03，git init/add/commit 在 API 请求路径中同步执行 |

### 2.5 `backend/tasks/clone_repo.py`

**正常点**
- 使用 `redis_lock` 防止并发克隆同一站点。
- 正确解密 `git_password_encrypted`（ISSUE-03）。
- 失败时设置 `SiteStatus.ERROR`，成功设置 `STOPPED`。

**问题**

| 编号 | 位置 | 描述 |
|------|------|------|
| R-11 | 第 17 行 | 使用 `AgentTask` 而非 `Task`；而 `task_service.serialize_task` 返回的字段期望 `Task` 模型上的属性，若字段不对齐会导致 KeyError 静默失败 |
| R-12 | 第 72 行 | `task_service.serialize_task(task)` 的返回值作为 Celery 任务结果，但无后续消费者读取此值；克隆进度/结果也没有通过 WebSocket 推送给前端，前端只能轮询站点状态 |

### 2.6 `backend/services/task_service.py`

- `enqueue_task` 中 `clone_repo` 分支正确调用 `clone_repo_task.delay()`。
- `SUPPORTED_TASK_TYPES` 包含 `"clone_repo"`，但 `create_task` 方法用于站点级任务，项目仓库克隆的任务不经此路径（由 `add_repo` 直接创建 `AgentTask`），存在两套任务模型并行问题（`Task` vs `AgentTask`）。

---

## 三、前端审查

### 3.1 `frontend/src/types/models.ts`

**正常点**
- `Project`、`ProjectCreateRequest`、`RepoAddRequest`、`Site` 定义完整，与后端 API 契约基本对齐。

**问题**

| 编号 | 位置 | 描述 |
|------|------|------|
| R-13 | `Site`（第 24 行） | `project_id?: string` 已声明，但后端 `serialize_site` 未输出该字段（见 R-09），导致前端始终得到 `undefined` |
| R-14 | `Site.status` | 类型为 `'running' | 'stopped' | 'failed' | 'building'`，但后端 `SiteStatus` 包含 `'error'` 而非 `'failed'`，类型不匹配 |
| R-15 | `Project` | 无 `updated_at` 渲染，但声明了 `updated_at?: string`；`ProjectList.vue` 也不显示，字段定义冗余但无害 |

### 3.2 `frontend/src/api/projects.ts`

**正常点**
- API 方法完整覆盖所有后端端点。
- 返回类型精确定义，使用范型。

**问题**
- `listRepoFiles` / `getRepoFile` 使用 `repoId`，实际传入的是 `site_id`（字符串形式的 UUID），与后端路径参数 `{repo_id}` 一致，命名稍有歧义但无功能问题。

### 3.3 `frontend/src/stores/project.ts`

**问题**

| 编号 | 位置 | 描述 |
|------|------|------|
| R-16 | `addRepo`（第 51 行） | 添加仓库成功后调用 `fetchProject(projectId)` 重新拉取整个项目，包括 N 个 repos；对于含 git clone 场景，仓库可能还在 `building` 状态，但 store 没有后续轮询机制，用户进入编辑器后可能遇到空文件树 |
| R-17 | `createProject`（第 40 行） | 创建后使用 `unshift` 插入列表头部，但后端 `list_projects` 按 `created_at.asc()` 排序，下次刷新顺序会变，视觉抖动 |

### 3.4 `frontend/src/views/Projects/ProjectDetail.vue`

**正常点**
- 添加仓库 Dialog 表单完整，包含 Git 认证字段。
- 仓库卡片展示 `status` 颜色区分（building/running/stopped）。

**问题**

| 编号 | 位置 | 描述 |
|------|------|------|
| R-18 | 第 69 行 | `"打开编辑器"` 按钮仅在 `project.repos?.length > 0` 时显示，但对 `building` 状态的仓库进入编辑器会得到空文件树，缺少克隆完成前的保护 |
| R-19 | - | 无仓库克隆进度实时反馈，用户不知道克隆何时完成（无轮询、无 WebSocket 订阅） |

### 3.5 `frontend/src/views/Projects/ProjectEditor.vue`

**正常点**
- 多仓库 Tab 切换设计合理（RepoTabs）。
- 文件已打开时切换到已有 Tab 而不重复请求（D-12 行为）。
- 语言映射覆盖常见扩展名。

**问题**

| 编号 | 位置 | 描述 |
|------|------|------|
| R-20 | 第 131-136 行 | 注释标注 `Monaco Editor readOnly`，但实际实现是 `<div class="p-4 text-sm font-mono whitespace-pre-wrap">`，用 div 渲染文本，Monaco 未集成，大文件渲染性能差，无语法高亮 |
| R-21 | `handleOpenFile`（第 57 行） | 二进制文件（`res.binary === true`）也会被打开，`res.content` 为空字符串，用户看到空白无任何提示 |
| R-22 | `handleOpenFile` | 无错误处理，若 `getRepoFile` 请求失败，tab 不会被关闭也不会提示错误 |

### 3.6 `frontend/src/views/Projects/components/RepoFileTree.vue`

**问题**

| 编号 | 位置 | 描述 |
|------|------|------|
| R-23 | `handleClick`（第 39 行） | 目录折叠时（`expandedDirs.delete`）不会清理子目录条目，`entries` 仍然是扁平列表；实际上目录展开/折叠仅靠 `expandedDirs` Set 状态，但 UI 渲染时没有使用该 Set 过滤，**折叠按钮没有视觉效果**，目录永远显示为展开 |
| R-24 | `loadFiles`（第 28 行） | 每次点击目录都替换整个 `entries`，不支持真正的树形嵌套展示；子目录打开会覆盖父级条目 |
| R-25 | - | 缺少空目录、加载错误的提示 |

### 3.7 `frontend/src/views/Projects/components/RepoTabs.vue`

- 实现简单清晰，`building` 状态有"克隆中..."标识，符合预期。
- 无问题。

### 3.8 `frontend/src/router/index.ts`

- Project 路由层级正确（`/projects`、`/projects/:id`、`/projects/:id/edit`）。
- `/sites` 重定向到 `/projects`，向后兼容。
- 使用 `// @ts-nocheck`，绕过类型检查，后续应逐步移除。

### 3.9 `frontend/src/components/Layout/AppLayout.vue`

- 侧边栏已新增"我的项目"入口，导航集成正确。
- 无问题。

---

## 四、测试覆盖分析（`backend/tests/test_projects.py`）

**覆盖良好**
- 项目 CRUD 完整测试（PROJ-01）。
- 空白仓库创建（PROJ-03）。
- 仓库名称非法字符验证（ISSUE-04）。
- 路径穿越防护（ISSUE-07）。
- 跨项目越权访问（NEW-03）。
- 未认证访问保护。

**测试缺口**

| 编号 | 缺失场景 |
|------|---------|
| T-01 | Git clone 异步任务的成功/失败流程（需 mock Celery/git） |
| T-02 | `building` 状态仓库在克隆完成前访问文件树的行为 |
| T-03 | 删除项目后磁盘文件是否清理（当前未清理，见 R-05） |
| T-04 | 同一项目下重名仓库的冲突处理（当前无唯一约束） |
| T-05 | 超级管理员跨用户访问项目权限 |

---

## 五、安全审查摘要

| 风险点 | 状态 |
|--------|------|
| 路径穿越（`../../`） | **已修复**（`resolve_site_path` + `relative_to` 校验） |
| 跨项目越权 | **已修复**（`site.project_id` 校验） |
| git_password 明文存储 | **已修复**（加密存 `git_password_encrypted`） |
| 仓库名称注入 | **已修复**（正则白名单验证） |
| Site 无端口分配（Repo 无需运行） | **正常**（port=NULL） |
| 超级管理员项目访问 | **未处理**（`get_project` 不检查 `is_superuser`，与 site_service 不一致） |
| API 请求路径中同步 git 操作 | **潜在风险**（阻塞，见 R-03/R-10） |

---

## 六、优先修复建议

### 高优先级（功能/安全）
1. **R-09**: `serialize_site` 补充输出 `project_id` 字段，修复前端类型声明不一致。
2. **R-14**: 前端 `Site.status` 类型补充 `'error'`（后端实际枚举值）。
3. **R-23/R-24**: `RepoFileTree` 文件树折叠逻辑和嵌套渲染是纯前端 BUG，需重写为树形数据结构。
4. **R-22**: `handleOpenFile` 增加 try/catch 错误处理和二进制文件提示（R-21）。
5. **R-16/R-19**: Git clone 仓库需有完成状态通知（轮询或 WebSocket），保护用户在 `building` 期间不进入编辑器。

### 中优先级（性能/体验）
6. **R-01/R-06**: `list_projects` N+1 查询改用 JOIN 或 subquery 一次拉取 repo count。
7. **R-05**: `delete_project` 补充磁盘清理（`shutil.rmtree(project_root)`）。
8. **R-03/R-10**: 空白仓库的 git init 改为异步任务，避免阻塞 API 响应。
9. **R-20**: `ProjectEditor` 集成真正的 Monaco Editor（readOnly 模式），当前用 div 渲染无高亮。

### 低优先级（代码质量）
10. **R-11**: 确认 `AgentTask` 与 `Task` 模型统一，消除两套任务模型并行问题。
11. **T-04**: 补充同项目下重名仓库唯一约束（DB 层或 Service 层）。
12. `router/index.ts` 移除 `@ts-nocheck`。

---

## 七、架构观察

- **Project 是 Site 的容器**：Site 表通过 `project_id` 外键归属项目，Project 无独立存储实体（文件），所有文件存在 repo（Site）目录下，路径规则为 `generated_sites/{project_id}/{repo_name}/`。此设计清晰但要求 `project_id` 不能变更（rename 不影响目录）。
- **两套任务模型并存**：`Task`（`backend/models/task.py`）用于 site 级 develop/deploy 任务；`AgentTask`（`backend/models/task.py` 同文件？）用于 clone_repo，需确认是否为同一模型或独立表，存在混用风险。
- **文件浏览走后端 API**：每次树展开都发 HTTP 请求，适合大型仓库但对频繁点击有延迟，可考虑根目录预加载。
