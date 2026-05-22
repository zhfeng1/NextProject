# 建站 Building 日志：设计文档

**日期**：2026-05-22  
**作者**：（设计协作）  
**目标**：新建站点（git clone）building 期间记录过程日志；前端点击 building 状态可弹窗实时查看。

## 背景

- 新建站点（`project_service.add_repo` + `git_url`）将 site 置为 `building`，由 Celery `clone_repo_task` 异步执行 git clone。
- 现有 `clone_repo_task` 不写过程日志，只在失败时把 error 字符串塞进 `task.payload_json`。
- 项目已有完整的 task 日志基础设施：`AgentTaskLog` 表、`/api/v2/tasks/{id}/logs` REST、`/ws/tasks/{id}/logs` WebSocket、前端 `TaskLogs.vue` + `useTaskLogs.ts`。这次需求绝大部分能直接复用。

## 决策

| 维度 | 决定 |
|------|------|
| 日志详细度 | 完整捕获 git 进程 stdout/stderr + 阶段日志（开始/克隆中/完成或失败） |
| 实时性 | WebSocket 流式推送，连接失败自动降级 REST 轮询（现有 `useTaskLogs` 已支持） |
| UI 形式 | 中央 Modal 弹窗，可复用组件 `BuildLogModal` |
| 覆盖范围 | 所有 building 状态出现点统一可点击：ProjectDetail、RepoTabs、SiteDetail、Dashboard 最近站点 |
| site → task 查找路径 | 复用现有 `GET /api/v2/tasks/site/{id}`，给该接口加可选 `task_type` 过滤参数 |

## 架构

```
点击 building
    ↓
BuildLogModal (新)
    ├─ ① GET /api/v2/tasks/site/{id}?task_type=clone_repo&limit=1
    │      → 拿 task_id
    └─ ② <TaskLogs :taskId/>  (现有组件)
                ↓
       WS /ws/tasks/{task_id}/logs  (现有)
                ↑ 写入
       clone_repo_task (改造)
          ├─ "开始克隆 {url} ({branch})"
          ├─ subprocess.Popen(git clone --progress) 逐行→ AgentTaskLog
          └─ 成功"克隆完成" / 失败"git clone 退出码 N"
```

## 改动点

### 后端

1. **`backend/tasks/clone_repo.py`** — 改造任务主体：
   - 任务开始时 `started_at = now()` + 写 INFO "开始克隆 ..."
   - `subprocess.Popen([git, "clone", "--progress", ...], stdout=PIPE, stderr=STDOUT, text=True, bufsize=1)`
   - 循环 `for line in proc.stdout`：每行 `rstrip()` 后用**独立短事务** `task_db_session()` insert 到 `agent_task_logs` 并 commit（这样 WS 才能立即读到）
   - 成功：site=STOPPED + INFO "克隆完成"；失败：site=ERROR + ERROR "git clone 退出码 N"
   - `finished_at = now()`

2. **`backend/services/task_service.py`** — `list_site_tasks` 增加可选 `task_type` 关键字参数：
   ```python
   async def list_site_tasks(self, db, site_id, current_user, *, limit=30, task_type=None):
       ...
       if task_type:
           query = query.where(AgentTask.task_type == task_type)
   ```

3. **`backend/api/v2/tasks.py`** — `GET /site/{site_id}` 加 query 参数 `task_type: str | None`，透传给 service。

### 前端

1. **新增 `frontend/src/components/BuildLogModal.vue`** — props `{ open, siteId, siteName? }`；open 时调一次 `listBySite(siteId, { task_type: 'clone_repo', limit: 1 })`，拿到 `task_id` 后渲染 `<TaskLogs :taskId/>`。

2. **`frontend/src/api/tasks.ts`** — 新增 `listBySite(siteId, { task_type?, limit? })` 方法。

3. **将 4 处 building 标签变可点击**，并挂载 `BuildLogModal`：
   - `views/Projects/ProjectDetail.vue` 仓库行
   - `views/Projects/components/RepoTabs.vue` Tab 上的 building 标记
   - `views/Sites/SiteDetail.vue` 状态徽章
   - `views/Dashboard/Index.vue` "最近站点" 项

## 错误处理

| 场景 | 处理 |
|------|------|
| building 状态但 task 还未入队（极短窗口） | Modal 显示"任务排队中" + 重试按钮 |
| WS 连接失败 | 现有 `useTaskLogs` 已自动降级 REST 轮询 |
| git progress 输出含 `\r` 控制字符 | `line.rstrip()` 处理；按行落库 |
| 进程意外卡死 / 任务超时 | 现有 Celery `default_retry_delay=30` + `max_retries=60` 保护；超时由 Celery 抛出，task 进入 FAILED，site 走 ERROR 分支 |
| site=error 时仍想看日志 | `AgentTaskLog` 永久保留，错误状态也可点击 |

## 测试

- **后端单测** `backend/tests/test_clone_repo_logs.py`：mock `subprocess.Popen` 模拟 git 输出（含成功 & 失败两条路径），断言 `AgentTaskLog` 行被插入、site/task 终态正确。
- **手工冒烟**：建项目 → 加 git 仓库 → 点击 building → modal 实时滚动 git progress；触发一次失败（错误 URL）→ 看 ERROR 日志。

## 不在本次范围

- 日志归档/压缩、保留期淘汰
- 日志全文搜索
- 其他类型 building（目前只有 git clone 会让 site=building）
- 重新触发构建（rebuild）按钮
