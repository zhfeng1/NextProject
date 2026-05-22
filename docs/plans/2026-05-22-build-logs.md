# 建站 Building 日志实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让新建站点（git clone）的 building 期间记录过程日志；前端点击 building 状态可弹窗实时查看。

**Architecture:** 后端在 `clone_repo_task` 用 `subprocess.Popen` 流式跑 git，每行 stdout/stderr 通过现有的 `task_service.append_log` 写入 `agent_task_logs` 并经 `websocket_manager.publish` 实时推送；前端新增轻量 `BuildLogModal.vue`，先调 `GET /api/v2/tasks/site/{id}?task_type=clone_repo&limit=1` 拿到 build task，再复用现有 `TaskLogs.vue` 经 WebSocket 接收。

**Tech Stack:** FastAPI / SQLAlchemy / Celery / Vue 3 / vue-router / WebSocket / Docker Compose

**Design doc:** `docs/plans/2026-05-22-build-logs-design.md`

**Working dir:** project root（无独立 worktree，用户授权一路实施）

---

## Task 1: 给 `list_site_tasks` 加 `task_type` 过滤参数（service 层）

**Files:**
- Modify: `backend/services/task_service.py:203-214`
- Test: `backend/tests/test_clone_repo_logs.py`（新建）

**Step 1: 写失败测试**

新建 `backend/tests/test_clone_repo_logs.py`：

```python
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_site_tasks_filters_by_task_type(app_module, authed_client):
    """list_site_tasks 接受 task_type kwarg 并按类型过滤"""
    # 准备：用 authed_client 在某个 project 下加一个 git 仓库（会创建 CLONE_REPO 任务）
    # 然后调 list_site_tasks 不带过滤、带过滤分别断言条数
    client = authed_client
    # 1) 建项目
    res = await client.post("/api/v2/projects", json={"name": "build-log-test"})
    assert res.status_code == 200, res.text
    project_id = res.json()["project"]["id"]

    # 2) 加 git 仓库（mock 不了 celery，但只看 task 是否落库；clone 入队即返回）
    res = await client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "repo-a", "git_url": "https://example.invalid/repo.git"},
    )
    assert res.status_code == 200, res.text
    site_id = res.json()["repo"]["site_id"]

    # 3) 不过滤：至少返回那条 clone_repo 任务
    res = await client.get(f"/api/v2/tasks/site/{site_id}")
    assert res.status_code == 200
    all_tasks = res.json()["tasks"]
    assert any(t["task_type"] == "clone_repo" for t in all_tasks)

    # 4) 按 task_type=clone_repo 过滤：只返回 clone_repo
    res = await client.get(f"/api/v2/tasks/site/{site_id}?task_type=clone_repo")
    assert res.status_code == 200
    filtered = res.json()["tasks"]
    assert filtered, "filtered list should not be empty"
    assert all(t["task_type"] == "clone_repo" for t in filtered)

    # 5) 不存在的类型：空列表
    res = await client.get(f"/api/v2/tasks/site/{site_id}?task_type=develop_code")
    assert res.json()["tasks"] == []
```

> 注：`authed_client` fixture 如果不存在，参照 `backend/tests/test_projects.py` 的写法（用 `app_module` + httpx AsyncClient + 注册/登录拿 token）。先看 `test_projects.py` 是怎么造 client 的，复用同款 fixture。

**Step 2: 跑测试，预期失败**

```bash
docker compose exec -T main-service pytest backend/tests/test_clone_repo_logs.py::test_list_site_tasks_filters_by_task_type -v
```
Expected: FAIL — 接口忽略 `task_type` 参数，返回全部任务。

**Step 3: 改 service 签名**

`backend/services/task_service.py:203-214`：

```python
async def list_site_tasks(
    self,
    db: AsyncSession,
    site_id: str,
    current_user: object,
    limit: int = 30,
    task_type: str | None = None,
) -> list[Task]:
    site = await site_service.get_site_by_public_id(db, site_id, current_user)
    query = select(Task).where(Task.site_id == site.id)
    if task_type:
        query = query.where(Task.task_type == task_type)
    query = query.order_by(desc(Task.created_at), desc(Task.id)).limit(limit)
    rows = await db.execute(query)
    return list(rows.scalars().all())
```

**Step 4: 改 API route**

`backend/api/v2/tasks.py:94-102`：

```python
@router.get("/site/{site_id}")
async def list_site_tasks(
    site_id: str,
    task_type: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tasks = await task_service.list_site_tasks(
        db, site_id, current_user, limit=limit, task_type=task_type
    )
    return {"ok": True, "site_id": site_id, "tasks": [task_service.serialize_task(t) for t in tasks]}
```

如果 v1 也有同样路由，同样补一份（grep `/api/v1/tasks.py` 看下，没有就不动）。

**Step 5: 跑测试，预期通过**

```bash
docker compose exec -T main-service pytest backend/tests/test_clone_repo_logs.py::test_list_site_tasks_filters_by_task_type -v
```
Expected: PASS

**Step 6: 提交**

```bash
git add backend/services/task_service.py backend/api/v2/tasks.py backend/tests/test_clone_repo_logs.py
git commit -m "feat(tasks): add task_type filter to list_site_tasks"
```

---

## Task 2: `clone_repo_task` 改造为流式写日志

**Files:**
- Modify: `backend/tasks/clone_repo.py`（重写主体）
- Test: `backend/tests/test_clone_repo_logs.py`（追加测试）

**Step 1: 写失败测试**

追加到 `backend/tests/test_clone_repo_logs.py`：

```python
import asyncio
from unittest.mock import patch, MagicMock


def _make_popen_mock(stdout_lines: list[str], returncode: int) -> MagicMock:
    """构造 Popen 替身：stdout 是可迭代的行序列，wait() 返回指定 rc"""
    proc = MagicMock()
    proc.stdout = iter(stdout_lines)
    proc.wait.return_value = returncode
    proc.returncode = returncode
    return proc


@pytest.mark.asyncio
async def test_clone_repo_task_writes_progress_logs_on_success(app_module, authed_client):
    """成功路径：git 每行 stdout 都落进 agent_task_logs，且最后 site=stopped"""
    from backend.services.task_service import task_service
    # 准备：建 project + 仓库 → 拿到 task_id
    res = await authed_client.post("/api/v2/projects", json={"name": "log-stream"})
    project_id = res.json()["project"]["id"]
    res = await authed_client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "repo", "git_url": "https://example.invalid/x.git"},
    )
    site_id_public = res.json()["repo"]["site_id"]
    # 拿到 task_id
    res = await authed_client.get(f"/api/v2/tasks/site/{site_id_public}?task_type=clone_repo")
    task_id = res.json()["tasks"][0]["id"]

    # 替换 Popen + 替换 clone 后的目录处理（防止真去操作文件系统）
    popen_mock = _make_popen_mock(
        ["Cloning into 'repo'...\n", "remote: Counting objects: 10\n", "Receiving objects: 100%\n"],
        returncode=0,
    )
    with patch("backend.tasks.clone_repo.subprocess.Popen", return_value=popen_mock), \
         patch("backend.tasks.clone_repo.Path.exists", return_value=True):
        from backend.tasks.clone_repo import clone_repo_task
        # 同步调用 celery task 的内部协程
        clone_repo_task.apply(args=[task_id]).get(disable_sync_subtasks=False)

    # 断言日志已写入
    res = await authed_client.get(f"/api/v2/tasks/{task_id}/logs")
    lines = [l["line"] for l in res.json()["logs"]]
    assert any("开始克隆" in l for l in lines), f"expect 开始克隆 log, got: {lines}"
    assert any("Cloning into" in l for l in lines), f"expect git output captured, got: {lines}"
    assert any("克隆完成" in l for l in lines), f"expect 克隆完成 log, got: {lines}"


@pytest.mark.asyncio
async def test_clone_repo_task_writes_error_log_on_failure(app_module, authed_client):
    """失败路径：rc != 0 时写 ERROR 日志，site=error"""
    res = await authed_client.post("/api/v2/projects", json={"name": "log-fail"})
    project_id = res.json()["project"]["id"]
    res = await authed_client.post(
        f"/api/v2/projects/{project_id}/repos",
        json={"name": "repo", "git_url": "https://example.invalid/y.git"},
    )
    site_id_public = res.json()["repo"]["site_id"]
    res = await authed_client.get(f"/api/v2/tasks/site/{site_id_public}?task_type=clone_repo")
    task_id = res.json()["tasks"][0]["id"]

    popen_mock = _make_popen_mock(
        ["fatal: repository not found\n"],
        returncode=128,
    )
    with patch("backend.tasks.clone_repo.subprocess.Popen", return_value=popen_mock):
        from backend.tasks.clone_repo import clone_repo_task
        with pytest.raises(Exception):  # task 会重新抛
            clone_repo_task.apply(args=[task_id]).get(disable_sync_subtasks=False)

    res = await authed_client.get(f"/api/v2/tasks/{task_id}/logs")
    log_levels = [(l["level"], l["line"]) for l in res.json()["logs"]]
    assert any(lvl == "ERROR" for lvl, _ in log_levels), f"expect ERROR level log, got: {log_levels}"

    # 站点状态应为 error
    res = await authed_client.get(f"/api/v2/sites/{site_id_public}")
    assert res.json()["site"]["status"] == "error"
```

**Step 2: 跑测试，预期失败**

```bash
docker compose exec -T main-service pytest backend/tests/test_clone_repo_logs.py -v
```
Expected: 后两条 FAIL（日志没写入、流式还没实现）

**Step 3: 改造 `clone_repo.py`**

完整替换 `backend/tasks/clone_repo.py`：

```python
from __future__ import annotations

import asyncio
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.core.celery_app import celery_app
from backend.core.redis_lock import acquire_site_lock, release_site_lock
from backend.models import AgentTask
from backend.models.enums import TaskStatus, SiteStatus
from backend.models.site import Site
from backend.tasks._helpers import task_db_session


@celery_app.task(bind=True, max_retries=60, default_retry_delay=30)
def clone_repo_task(self, task_id: str) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        # 1) 取 task 基础信息 + lock
        async with task_db_session() as db:
            task = await db.get(AgentTask, task_id)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            site_id_internal = str(task.site_id)

        if not acquire_site_lock(site_id_internal, task_id):
            raise self.retry(countdown=30)

        try:
            # 2) 标记 running + 开始日志
            async with task_db_session() as db:
                task = await db.get(AgentTask, task_id)
                site = await db.get(Site, str(task.site_id))
                if site is None:
                    raise ValueError(f"Site not found: {task.site_id}")

                payload = task.payload_json or {}
                git_url = payload.get("git_url", "")
                git_branch = payload.get("git_branch", "")
                git_username = payload.get("git_username", "")
                project_id = payload.get("project_id", "")
                repo_name = payload.get("repo_name", site.name)

                git_password = ""
                encrypted_pw = payload.get("git_password_encrypted", "")
                if encrypted_pw:
                    from backend.core.encryption import decrypt_api_key
                    git_password = decrypt_api_key(encrypted_pw)

                task.status = TaskStatus.RUNNING.value
                task.started_at = datetime.now(timezone.utc)
                await db.commit()

                from backend.services.task_service import task_service
                await task_service.append_log(
                    db, task,
                    f"开始克隆 {git_url} (branch={git_branch or 'default'})",
                    level="INFO", source="clone",
                )

            # 3) 跑 git clone（流式抓输出）
            from backend.services.site_service import site_service
            from backend.services.project_service import project_service

            clone_root = (
                project_service.repo_root(project_id, repo_name) if project_id
                else site_service.site_root(site.site_id)
            )

            git_bin = shutil.which("git")
            if not git_bin:
                raise RuntimeError("git is required in the runtime image to clone site repositories")

            # 清理目标目录（如果存在）
            if Path(clone_root).exists():
                shutil.rmtree(clone_root, ignore_errors=True)
            Path(clone_root).parent.mkdir(parents=True, exist_ok=True)

            clone_url = site_service._build_authenticated_git_url(git_url, git_username, git_password)
            cmd = [git_bin, "clone", "--progress"]
            if git_branch:
                cmd.extend(["--branch", git_branch, "--single-branch"])
            cmd.extend([clone_url, str(clone_root)])

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            try:
                for raw in proc.stdout:
                    line = raw.rstrip("\r\n")
                    if not line:
                        continue
                    # 短事务写一条日志（让 WS 立即看到）
                    async with task_db_session() as db:
                        task = await db.get(AgentTask, task_id)
                        from backend.services.task_service import task_service
                        await task_service.append_log(
                            db, task, line, level="INFO", source="git",
                        )
                rc = proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

            # 4) 收尾
            async with task_db_session() as db:
                task = await db.get(AgentTask, task_id)
                site = await db.get(Site, str(task.site_id))
                from backend.services.task_service import task_service

                if rc == 0:
                    # 校验 .git 目录存在
                    if not (Path(clone_root) / ".git").exists():
                        site.status = SiteStatus.ERROR.value
                        task.status = TaskStatus.FAILED.value
                        task.error = "Cloned repository is missing .git metadata"
                        task.finished_at = datetime.now(timezone.utc)
                        await task_service.append_log(
                            db, task, task.error, level="ERROR", source="clone",
                        )
                        await db.commit()
                        raise RuntimeError(task.error)

                    # 让 site_service 补全文档/np 目录
                    site_service._ensure_docs_structure(Path(clone_root))
                    site_service._ensure_np_structure(Path(clone_root))

                    site.status = SiteStatus.STOPPED.value
                    task.status = TaskStatus.SUCCESS.value
                    task.finished_at = datetime.now(timezone.utc)
                    await task_service.append_log(
                        db, task, "克隆完成", level="INFO", source="clone",
                    )
                else:
                    site.status = SiteStatus.ERROR.value
                    task.status = TaskStatus.FAILED.value
                    task.error = f"git clone 退出码 {rc}"
                    task.finished_at = datetime.now(timezone.utc)
                    await task_service.append_log(
                        db, task, task.error, level="ERROR", source="clone",
                    )
                    await db.commit()
                    raise RuntimeError(task.error)

                await db.commit()
                return task_service.serialize_task(task)
        finally:
            release_site_lock(site_id_internal, task_id)

    return asyncio.run(_run())
```

> **重要**：检查 `site_service._build_authenticated_git_url` 和 `_ensure_docs_structure` / `_ensure_np_structure` 是否真存在（前面 grep 看到 `_ensure_docs_structure` 和 `_ensure_np_structure` 在 site_service.py:210-211 调用，方法本身要确认是公开还是私有）。

**Step 4: 跑测试，预期通过**

```bash
docker compose exec -T main-service pytest backend/tests/test_clone_repo_logs.py -v
```
Expected: ALL PASS

**Step 5: 提交**

```bash
git add backend/tasks/clone_repo.py backend/tests/test_clone_repo_logs.py
git commit -m "feat(clone_repo): stream git output to agent_task_logs"
```

---

## Task 3: 前端 `tasksAPI.listBySite` 支持 `task_type`

**Files:**
- Modify: `frontend/src/api/tasks.ts:80-84`

**Step 1: 修改签名**

替换 `listBySite` 为：

```typescript
listBySite(siteId: string, opts: { task_type?: string; limit?: number } = {}) {
  const params = new URLSearchParams()
  if (opts.task_type) params.set('task_type', opts.task_type)
  params.set('limit', String(opts.limit ?? 10))
  return client.get<any, { ok: boolean; tasks: Task[] }>(
    `/tasks/site/${siteId}?${params.toString()}`,
  )
},
```

**Step 2: 兼容现有调用方**

grep 找现有 `listBySite` 调用：

```bash
grep -rn "tasksAPI.listBySite\|tasks\.listBySite" frontend/src/ --include="*.vue" --include="*.ts"
```

把每个调用处从 `listBySite(siteId, 20)` 改成 `listBySite(siteId, { limit: 20 })`。

**Step 3: 类型检查**

```bash
cd frontend && npx vue-tsc -b --noEmit
```
Expected: 无错误

**Step 4: 提交**

```bash
git add frontend/src/api/tasks.ts frontend/src/  # 把现有调用方修复也一并提交
git commit -m "refactor(api): tasksAPI.listBySite accepts options object"
```

---

## Task 4: 新增 `BuildLogModal.vue` 组件

**Files:**
- Create: `frontend/src/components/BuildLogModal.vue`

**Step 1: 写组件**

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import TaskLogs from '@/components/TaskLogs.vue'
import { tasksAPI } from '@/api/tasks'

const props = defineProps<{
  open: boolean
  siteId: string
  siteName?: string
}>()

const emit = defineEmits<{
  'update:open': [boolean]
}>()

const taskId = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function load() {
  if (!props.open || !props.siteId) return
  loading.value = true
  errorMsg.value = ''
  taskId.value = ''
  try {
    const res = await tasksAPI.listBySite(props.siteId, {
      task_type: 'clone_repo',
      limit: 1,
    })
    const t = res.tasks?.[0]
    if (!t) {
      errorMsg.value = '尚未找到构建任务，可能还在排队，稍后再试'
    } else {
      taskId.value = t.id
    }
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || e?.message || '加载构建任务失败'
  } finally {
    loading.value = false
  }
}

watch(() => [props.open, props.siteId], load, { immediate: true })
</script>

<template>
  <Dialog :open="open" @update:open="(v: boolean) => emit('update:open', v)">
    <DialogContent class="max-w-3xl p-0">
      <DialogHeader class="px-6 pt-6 pb-2">
        <DialogTitle>构建日志 — {{ siteName || siteId }}</DialogTitle>
      </DialogHeader>
      <div class="px-6 pb-6">
        <div v-if="loading" class="py-12 text-center text-sm text-muted-foreground">
          加载构建任务中…
        </div>
        <div v-else-if="errorMsg" class="py-12 text-center text-sm text-destructive">
          {{ errorMsg }}
          <div class="mt-3">
            <button class="text-xs underline text-muted-foreground" @click="load">重试</button>
          </div>
        </div>
        <div v-else-if="taskId" class="h-[60vh]">
          <TaskLogs :task-id="taskId" />
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
```

**Step 2: 类型检查**

```bash
cd frontend && npx vue-tsc -b --noEmit
```
Expected: 无错误

**Step 3: 提交**

```bash
git add frontend/src/components/BuildLogModal.vue
git commit -m "feat(frontend): add BuildLogModal for viewing clone progress"
```

---

## Task 5: 在 ProjectDetail.vue 中接入

**Files:**
- Modify: `frontend/src/views/Projects/ProjectDetail.vue`

**Step 1: script 中加 state**

在 `<script setup>` 顶部加 import 与 ref：

```typescript
import BuildLogModal from '@/components/BuildLogModal.vue'

const buildLogOpen = ref(false)
const buildLogSiteId = ref('')
const buildLogSiteName = ref('')

function openBuildLog(siteId: string, name: string) {
  buildLogSiteId.value = siteId
  buildLogSiteName.value = name
  buildLogOpen.value = true
}
```

**Step 2: 改 building span（123 行附近）变可点击**

把：

```vue
<span :class="repo.status === 'building' ? 'text-yellow-500' : repo.status === 'running' ? 'text-green-500' : repo.status === 'error' ? 'text-red-500' : 'text-gray-500'">
  {{ repo.status }}
</span>
```

改成：

```vue
<button
  v-if="repo.status === 'building'"
  type="button"
  class="text-yellow-500 underline-offset-2 hover:underline cursor-pointer"
  @click.stop="openBuildLog(repo.site_id, repo.name)"
>
  {{ repo.status }}（点击查看日志）
</button>
<span
  v-else
  :class="repo.status === 'running' ? 'text-green-500' : repo.status === 'error' ? 'text-red-500' : 'text-gray-500'"
>
  {{ repo.status }}
</span>
```

**Step 3: template 底部挂 modal**

在 `<template>` 最外层（最末尾、根 `</div>` 前）加：

```vue
<BuildLogModal
  v-model:open="buildLogOpen"
  :site-id="buildLogSiteId"
  :site-name="buildLogSiteName"
/>
```

**Step 4: 类型检查**

```bash
cd frontend && npx vue-tsc -b --noEmit
```
Expected: 无错误

**Step 5: 提交**

```bash
git add frontend/src/views/Projects/ProjectDetail.vue
git commit -m "feat(projects): wire BuildLogModal into ProjectDetail building badge"
```

---

## Task 6: 在 RepoTabs.vue 中接入

**Files:**
- Modify: `frontend/src/views/Projects/components/RepoTabs.vue`

**Step 1: 让组件能 emit 一个查看日志事件（不直接挂 modal，由父组件控）**

把 `defineEmits` 改成：

```typescript
const emit = defineEmits<{
  (e: 'select', repoId: string): void
  (e: 'viewBuildLog', repo: Site): void
}>()
```

把 `<span v-if="repo.status === 'building'" ...>` 改成 button：

```vue
<button
  v-if="repo.status === 'building'"
  type="button"
  class="ml-1 text-xs text-yellow-500 underline-offset-2 hover:underline"
  @click.stop="emit('viewBuildLog', repo)"
>克隆中... 查看</button>
```

**Step 2: 在 RepoTabs 的使用方挂上事件**

grep 找用 RepoTabs 的地方：

```bash
grep -rn "RepoTabs" frontend/src/ --include="*.vue"
```

在那个父组件（很可能是 ProjectEditor.vue 或类似）里：
- import `BuildLogModal`
- 加 state（同 Task 5）
- 在 `<RepoTabs ... @viewBuildLog="(r) => openBuildLog(r.site_id, r.name)" />`
- template 底部挂 `<BuildLogModal v-model:open=... />`

**Step 3: 类型检查 + 提交**

```bash
cd frontend && npx vue-tsc -b --noEmit
git add frontend/src/views/Projects/components/RepoTabs.vue frontend/src/views/Projects/<parent>.vue
git commit -m "feat(projects): wire BuildLogModal into RepoTabs"
```

---

## Task 7: 在 SiteDetail.vue 中接入

**Files:**
- Modify: `frontend/src/views/Sites/SiteDetail.vue`

**Step 1: script 加 import + state**

同 Task 5，加 `BuildLogModal` import 和 `buildLogOpen` 三个 ref + `openBuildLog` 函数。

**Step 2: 改第 93-94 行的 status span**

把：

```vue
<span :class="site.status === 'running' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'" class="px-3 py-1 text-sm rounded font-medium">
  {{ statusLabel }}
</span>
```

改成：

```vue
<button
  v-if="site.status === 'building'"
  type="button"
  class="px-3 py-1 text-sm rounded font-medium bg-yellow-100 text-yellow-700 hover:bg-yellow-200"
  @click="openBuildLog(site.site_id, site.name)"
>
  {{ statusLabel }}（点击查看日志）
</button>
<span
  v-else
  :class="site.status === 'running' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'"
  class="px-3 py-1 text-sm rounded font-medium"
>
  {{ statusLabel }}
</span>
```

**Step 3: template 底部挂 modal**

同 Task 5。

**Step 4: 类型检查 + 提交**

```bash
cd frontend && npx vue-tsc -b --noEmit
git add frontend/src/views/Sites/SiteDetail.vue
git commit -m "feat(sites): wire BuildLogModal into SiteDetail status badge"
```

---

## Task 8: 在 Dashboard/Index.vue 的"最近站点"接入

**Files:**
- Modify: `frontend/src/views/Dashboard/Index.vue`

**Step 1: script 加 import + state**

同 Task 5。

**Step 2: 改 438 行附近的 status badge**

最近站点条目是一个 `<button>`（428-444 行），整体点击会跳 SiteEditor。要让"building 徽章"成为一个独立可点击区域而不触发外层导航——给徽章包一层 `<span @click.stop>`，并把 button 标签内 building 时改成 `<span @click.stop="..." class="cursor-pointer">`：

把：

```vue
<span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{{ siteStatusLabel(site.status) }}</span>
```

改成：

```vue
<span
  v-if="site.status === 'building'"
  class="rounded-full bg-yellow-100 px-2 py-0.5 text-[11px] text-yellow-700 cursor-pointer hover:bg-yellow-200"
  @click.stop="openBuildLog(site.site_id, site.name)"
>
  {{ siteStatusLabel(site.status) }}（查看日志）
</span>
<span
  v-else
  class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
>
  {{ siteStatusLabel(site.status) }}
</span>
```

**Step 3: template 底部挂 modal**

同 Task 5。

**Step 4: 类型检查 + 提交**

```bash
cd frontend && npx vue-tsc -b --noEmit
git add frontend/src/views/Dashboard/Index.vue
git commit -m "feat(dashboard): wire BuildLogModal into recent sites building badge"
```

---

## Task 9: 重建镜像并冒烟

**Step 1: 重建并重启**

```bash
docker compose up -d --build main-service celery-worker frontend
```

按用户偏好规则：代码改完必须重启对应服务。`main-service`（API） / `celery-worker`（跑 clone_repo_task） / `frontend`（rebuild dist）。

**Step 2: 冒烟**

浏览器打开 http://localhost:20100：

1. 登录 → 进入"我的项目" → 新建一个项目 → "添加仓库" 输入一个**故意错误**的 git URL（例如 `https://example.invalid/x.git`）
2. 仓库卡片状态应显示 `building（点击查看日志）` 黄色按钮 → 点击
3. modal 应弹出，先看到 "开始克隆 …" INFO，然后是 git 失败输出，最后是 "git clone 退出码 128" ERROR
4. 关闭 modal，等几秒，状态应变成 `error`
5. 再点击徽章，仍能查看历史日志

如果用一个真实可访问的小仓库（如 `https://github.com/octocat/Hello-World.git`），应能看到 git progress 行流式滚动 → 最后 "克隆完成" + 状态变 `stopped`。

**Step 3: 跑全量后端测试**

```bash
docker compose exec -T main-service pytest backend/tests/ -x --timeout=60
```
Expected: 全绿（至少 `test_clone_repo_logs.py` 全通过，其他不退化）

**Step 4: 提交 final 校验**

无新文件需要提交（已经按任务步骤逐个提交）。检查 `git status` 应该 clean。

---

## 回归保护

- `task_service.append_log` 已有现成实现，本计划复用而非新增。
- `subprocess.run` 调用 git 的旧路径在 `site_service.clone_site_repository` 仍保留（其他场景比如直接建站点会用到），不在本计划改动范围。
- `site_service._build_authenticated_git_url` 等私有方法被 clone_repo.py 调用——如果方法不存在或签名不一致，stop and ask；不要硬塞实现。

## 实施完成后

回显给用户：
- 改了哪几个文件、跑了几条测试
- 冒烟链接：http://localhost:20100 → 我的项目 → 加 git 仓库 → 点击 building
