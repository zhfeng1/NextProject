# 📋 实施计划：Site Builder V2 — 编写→测试→部署一条龙

> 生成时间：2025-03
> 分析来源：Codex 后端分析（SESSION_ID: 019cffff-a466-7313-a3d3-0caf2e26c4e4）+ Claude 前端分析
> Gemini：认证账号暂不可用，前端部分由 Claude 独立完成

---

## 任务类型
- [x] 后端 (→ Codex)
- [x] 前端 (→ Claude/Codex 协作，Gemini 暂不可用)
- [x] 全栈并行

---

## 现状总结

| 层 | 现状 | 主要缺陷 |
|---|---|---|
| 后端 | FastAPI + SQLite，单文件 1913行 | 任务单次无上下文、日志轮询、无流水线、需求仅 notes |
| 前端 | Jinja2 + Vue3 CDN，4个多页模板 | 无构建工具、无 TypeScript、无路由、轮询日志 |
| 基础设施 | Docker Compose（2容器）| SQLite 无 WAL、无索引优化 |

---

## 技术方案（综合 Codex 分析）

### 核心架构原则
- **SQLite 作为权威状态库**，文件（REQUIREMENTS.md 等）作为可读产物
- **进程内事件总线**作为 WebSocket 实时层（单进程，不引入 Redis）
- **现有 `agent_tasks` 作为执行层**，新增 pipeline 调度层
- **主要变更**：补索引→WebSocket→对话上下文→需求归档→流水线编排

---

## 实施步骤（按阶段）

---

### 阶段一：基础设施增强（后端 Codex 主导）

**目标**：数据库 Schema 升级 + SQLite 性能优化，为后续阶段铺路

#### 步骤 1.1 SQLite 性能优化

```python
# startup() 中增加
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
conn.execute("PRAGMA synchronous=NORMAL")
```

**预期产物**：写并发能力提升，WAL 模式开启

#### 步骤 1.2 数据库 Schema 扩展

新增以下表：

```sql
-- 日志索引补充
CREATE INDEX IF NOT EXISTS idx_task_logs_task_id ON agent_task_logs(task_id, id);

-- 多轮对话
CREATE TABLE IF NOT EXISTS site_conversations (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    title TEXT DEFAULT '新会话',
    status TEXT DEFAULT 'active',     -- active | archived
    summary_text TEXT DEFAULT '',     -- 滚动摘要
    last_message_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS site_conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,               -- user | assistant | system | tool
    content TEXT NOT NULL,
    message_type TEXT DEFAULT 'text', -- text | task_ref | requirement_event
    provider TEXT DEFAULT '',
    task_id TEXT DEFAULT '',
    token_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT DEFAULT '{}'
);

-- 需求事件溯源
CREATE TABLE IF NOT EXISTS site_requirement_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    event_type TEXT NOT NULL,         -- user_input | llm_edit | task_result | manual
    content TEXT NOT NULL,            -- 原始指令/内容
    source TEXT DEFAULT '',           -- conversation_id / task_id / api
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS site_requirement_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    version_num INTEGER NOT NULL,
    title TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    content_md TEXT NOT NULL,         -- 结构化需求快照（Markdown）
    is_current INTEGER DEFAULT 0,     -- 1=当前版本
    trigger_event_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 流水线
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    name TEXT DEFAULT '开发→测试→部署',
    status TEXT NOT NULL DEFAULT 'pending', -- pending|running|success|failed|canceled
    trigger_mode TEXT DEFAULT 'manual',
    error TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    finished_at DATETIME
);

CREATE TABLE IF NOT EXISTS pipeline_run_steps (
    id TEXT PRIMARY KEY,
    pipeline_run_id TEXT NOT NULL,
    step_key TEXT NOT NULL,           -- develop | test | deploy
    step_index INTEGER NOT NULL,
    task_type TEXT NOT NULL,
    provider TEXT DEFAULT '',
    config_json TEXT DEFAULT '{}',
    depends_on_json TEXT DEFAULT '[]',-- 依赖的 step_key 列表
    status TEXT DEFAULT 'pending',    -- pending|running|success|failed|canceled|skipped
    task_id TEXT DEFAULT '',          -- 对应的 agent_task.id
    on_failure TEXT DEFAULT 'stop',   -- stop | skip | continue
    retry_limit INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    finished_at DATETIME
);
```

同时给 `agent_tasks` 补充关联字段：
```sql
ALTER TABLE agent_tasks ADD COLUMN pipeline_run_id TEXT DEFAULT '';
ALTER TABLE agent_tasks ADD COLUMN pipeline_step_id TEXT DEFAULT '';
ALTER TABLE agent_tasks ADD COLUMN conversation_id TEXT DEFAULT '';
ALTER TABLE agent_tasks ADD COLUMN requirement_version_id INTEGER DEFAULT 0;
```

**预期产物**：完整 Schema v2，向前兼容

#### 步骤 1.3 后端模块拆分

将 `main.py` 拆分为：

```
main_service/app/
├── main.py              # 仅保留 FastAPI app 实例、startup/shutdown、路由注册
├── db.py                # SQLite 连接、init_db、Schema
├── models.py            # Pydantic 模型（请求/响应）
├── sites.py             # 站点 CRUD、进程管理
├── tasks.py             # 任务队列、Worker、execute_xxx
├── conversations.py     # 多轮对话逻辑
├── requirements_mgr.py  # 需求事件归档、版本快照
├── pipelines.py         # 流水线调度器
├── ws.py                # WebSocket 连接管理器
├── llm.py               # LLM 调用封装
└── deploy.py            # Apollo/Local 部署逻辑
```

**预期产物**：模块化后端，main.py < 100行

---

### 阶段二：实时日志 WebSocket（后端 Codex + 前端 Claude）

**目标**：任务日志从"前端轮询"升级为"WebSocket 实时推送"

#### 步骤 2.1 后端 WebSocket 端点

```python
# ws.py - ConnectionManager
class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}   # task_id -> [ws]
        self._lock = threading.Lock()

    async def connect(self, task_id: str, ws: WebSocket):
        await ws.accept()
        with self._lock:
            self._connections.setdefault(task_id, []).append(ws)

    def broadcast_sync(self, task_id: str, data: dict):
        """从 worker thread 调用，桥接到 async"""
        # 通过 asyncio.run_coroutine_threadsafe 推送
        ...

    async def disconnect(self, task_id: str, ws: WebSocket):
        ...

# 新增端点
@app.websocket("/ws/tasks/{task_id}/logs")
async def ws_task_logs(task_id: str, ws: WebSocket, after_id: int = 0):
    await manager.connect(task_id, ws)
    # 1. 先回放历史（after_id 之后）
    # 2. 订阅实时增量
    # 3. 保活心跳（30s）
    # 4. 断开清理
```

**REST `/api/tasks/{id}/logs` 保留**，作为历史回放和降级链路

#### 步骤 2.2 修改 `append_task_log()`

```python
def append_task_log(task_id: str, line: str, level: str = "INFO") -> None:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(...)
        log_id = cursor.lastrowid
        conn.commit()
    # 新增：广播给 WS 订阅者
    manager.broadcast_sync(task_id, {
        "id": log_id, "level": level, "line": line, "ts": now_iso()
    })
```

#### 步骤 2.3 前端 WebSocket 客户端

```typescript
// composables/useTaskLogs.ts
export function useTaskLogs(taskId: Ref<string>) {
    const logs = ref<LogEntry[]>([])
    let ws: WebSocket | null = null
    let reconnectTimer: number | null = null

    function connect(afterId = 0) {
        ws = new WebSocket(`ws://${location.host}/ws/tasks/${taskId.value}/logs?after_id=${afterId}`)
        ws.onmessage = (e) => {
            const entry = JSON.parse(e.data)
            if (entry.type === 'resync_required') {
                // 队列满，走 REST 补历史
                fallbackFetch()
            } else {
                logs.value.push(entry)
            }
        }
        ws.onclose = () => {
            // 断线重连（指数退避）
            reconnectTimer = setTimeout(() => connect(lastId), backoff())
        }
    }

    onUnmounted(() => { ws?.close() })
    return { logs, connect }
}
```

**预期产物**：
- `/ws/tasks/{id}/logs` 端点
- 前端 `useTaskLogs` composable
- 日志面板实时无抖动渲染

---

### 阶段三：AI 多轮对话（全栈）

**目标**：将"单次 prompt → CLI"升级为"有上下文的多轮对话开发"

#### 步骤 3.1 后端对话 API

```
POST   /api/sites/{site_id}/conversations          # 创建会话
GET    /api/sites/{site_id}/conversations          # 会话列表
GET    /api/conversations/{conv_id}                # 会话详情+消息
POST   /api/conversations/{conv_id}/messages       # 发送消息（触发 develop_code）
GET    /api/conversations/{conv_id}/messages       # 消息历史
DELETE /api/conversations/{conv_id}                # 归档会话
```

#### 步骤 3.2 上下文拼装逻辑

```python
def build_context_prompt(conv_id: str, user_message: str, site_id: str) -> str:
    """
    系统提示（当前需求版本）
    + 会话摘要（如果历史超过 N 轮）
    + 最近 K 轮消息（role: user/assistant）
    + 当前用户消息
    """
    requirement = get_current_requirement(site_id)   # 最新需求版本 Markdown
    summary = get_conversation_summary(conv_id)
    recent_messages = get_recent_messages(conv_id, limit=10)

    system_prompt = f"""你是站点开发助手，当前站点需求如下：
{requirement}

请根据对话历史和用户最新指令修改站点代码。"""

    context = "\n".join([f"{m['role']}: {m['content']}" for m in recent_messages])
    return f"{system_prompt}\n\n{context}\nuser: {user_message}"
```

**Token 预算**：超过 8000 token 时自动触发摘要滚动（调用 LLM 生成 summary）

#### 步骤 3.3 前端对话 UI

```
┌─────────────────────────────────────────────┐
│  💬 开发对话  [新建会话]  [历史会话 ▼]       │
├─────────────────────────────────────────────┤
│  🤖 当前需求：xx需求（版本3）                │
│─────────────────────────────────────────────│
│  👤 用户：添加用户登录功能                   │
│  🤖 Codex：已修改 backend/app.py...        │
│     [查看任务日志 →]  [任务 #abc 成功 ✓]   │
│  👤 用户：登录按钮颜色改成蓝色              │
│  🤖 Codex：正在修改... [实时日志 ↓]        │
│─────────────────────────────────────────────│
│  选择 Provider: [Codex ▼]                  │
│  [___________________________________] [发送] │
└─────────────────────────────────────────────┘
```

**组件**：`ConversationPanel.vue`、`MessageBubble.vue`、`TaskInlineLog.vue`

**预期产物**：
- 多轮对话 API（6个端点）
- 上下文拼装逻辑 + 摘要滚动
- 对话气泡 UI 组件

---

### 阶段四：需求自动整理归档（全栈）

**目标**：每次用户输入/调整自动触发需求事件记录，生成结构化版本快照

#### 步骤 4.1 事件溯源钩子

在以下接口调用时自动记录 `site_requirement_events`：
- `POST /api/conversations/{id}/messages`（用户发送消息）
- `POST /api/sites/{id}/llm-action`（LLM 编辑）
- `POST /api/adjust-site`（调整接口）
- `POST /api/build-site`（初始生成）

#### 步骤 4.2 版本快照生成

```python
def generate_requirement_version(site_id: str, trigger_event_id: int) -> int:
    """
    调用 LLM：将所有历史 requirement_events 归纳为结构化 Markdown
    格式：
    ## 功能需求
    - ...
    ## UI 要求
    - ...
    ## 技术约束
    - ...
    ## 变更历史
    - vN: ...
    """
    events = get_all_events(site_id)
    prompt = f"整理以下开发历史为结构化需求文档：\n{events}"
    content_md = call_llm_content(cfg, prompt)

    # 物化到文件
    requirements_file = site_root(site_id) / "REQUIREMENTS.md"
    requirements_file.write_text(content_md)

    # 存版本快照
    version_num = get_next_version_num(site_id)
    save_requirement_version(site_id, version_num, content_md, trigger_event_id)
    return version_num
```

**触发策略**：每 5 次用户事件或手动触发一次版本生成（避免频繁 LLM 调用）

#### 步骤 4.3 需求面板 UI

```
┌──────────────────────────┐
│  📋 需求归档             │
│  当前版本：v5            │
│─────────────────────────│
│  ## 功能需求             │
│  - 用户登录/注册         │
│  - 商品列表页            │
│  - 购物车                │
│                          │
│  ## 变更历史             │
│  v5: 添加购物车 (今天)   │
│  v4: 商品列表 (昨天)     │
│  v3: 登录功能            │
│  [查看完整版本 →]        │
│─────────────────────────│
│  [手动触发归档]          │
└──────────────────────────┘
```

**预期产物**：
- 需求事件自动记录钩子
- LLM 驱动的版本快照生成
- `REQUIREMENTS.md` 物化文件
- 需求归档侧边栏组件

---

### 阶段五：流水线编排（后端 Codex 主导）

**目标**：支持"开发→测试→部署"一条龙自动串联，底层按 DAG 模型实现

#### 步骤 5.1 流水线调度器

```python
# pipelines.py
PIPELINE_TEMPLATES = {
    "full": [
        {"step_key": "develop", "task_type": "develop_code",          "depends_on": []},
        {"step_key": "test",    "task_type": "test_local_playwright",  "depends_on": ["develop"]},
        {"step_key": "deploy",  "task_type": "deploy_local",           "depends_on": ["test"], "on_failure": "stop"},
    ],
    "deploy_apollo": [
        {"step_key": "develop", "task_type": "develop_code",           "depends_on": []},
        {"step_key": "test",    "task_type": "test_local_playwright",  "depends_on": ["develop"]},
        {"step_key": "deploy",  "task_type": "deploy_apollo",          "depends_on": ["test"]},
    ],
    "dev_only": [
        {"step_key": "develop", "task_type": "develop_code",           "depends_on": []},
    ],
}

class PipelineScheduler:
    def tick(self, pipeline_run_id: str) -> None:
        """每次任务状态变更后调用，推进流水线状态机"""
        steps = get_pipeline_steps(pipeline_run_id)
        for step in steps:
            if step.status == "pending" and all_deps_success(step, steps):
                enqueue_step_as_task(step)
            elif step.status == "failed" and step.on_failure == "stop":
                cancel_remaining_steps(pipeline_run_id)
```

#### 步骤 5.2 流水线 API

```
POST /api/sites/{site_id}/pipelines              # 创建流水线（指定模板+prompt）
GET  /api/sites/{site_id}/pipelines              # 流水线历史
GET  /api/pipelines/{pipeline_run_id}            # 流水线详情+steps
POST /api/pipelines/{pipeline_run_id}/cancel     # 取消流水线
```

#### 步骤 5.3 流水线面板 UI

```
┌──────────────────────────────────────────────────────────┐
│  🚀 一键部署流水线                          [新建流水线] │
│──────────────────────────────────────────────────────────│
│  流水线 #3  2025-03-xx  apollo部署         [取消]       │
│                                                          │
│  ① 开发 (Codex)  ──────►  ② 测试 (Playwright)  ──► ③ Apollo 部署  │
│  [✓ 成功 2min]           [⟳ 运行中...]              [等待中]      │
│                          [查看日志 ↓]                              │
│  ─────────────────────────────────────────────────────── │
│  流水线 #2  成功 ✓                                       │
│  流水线 #1  失败 ✗  测试阶段失败                         │
└──────────────────────────────────────────────────────────┘
```

**预期产物**：
- `PipelineScheduler` 调度器 + 3种流水线模板
- 流水线 API（4个端点）
- 流水线可视化面板组件

---

### 阶段六：前端 SPA 重构（Claude 主导）

**目标**：用 Vue3 + Vite + TypeScript 重构前端，保持暖橙色 UI 风格

#### 步骤 6.1 项目结构

```
main_service/frontend/          # 新 SPA 目录（与 app/ 并列）
├── package.json
├── vite.config.ts              # 代理到 :8080 后端
├── tsconfig.json
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── router/index.ts
│   ├── stores/                 # Pinia
│   │   ├── site.ts
│   │   ├── tasks.ts
│   │   └── conversation.ts
│   ├── composables/
│   │   ├── useTaskLogs.ts      # WebSocket 日志
│   │   ├── usePipeline.ts
│   │   └── useConversation.ts
│   ├── pages/
│   │   ├── ConfigPage.vue      # /config
│   │   ├── HomePage.vue        # /home
│   │   ├── SiteEditorPage.vue  # /site/:id/editor
│   │   └── SiteConfigPage.vue  # /site/:id/config
│   └── components/
│       ├── ConversationPanel.vue
│       ├── MessageBubble.vue
│       ├── TaskLogPane.vue
│       ├── PipelinePanel.vue
│       ├── RequirementsPanel.vue
│       ├── SitePreview.vue
│       └── SiteCard.vue
```

#### 步骤 6.2 路由结构

```typescript
const routes = [
    { path: '/',              component: ConfigPage },
    { path: '/home',          component: HomePage },
    { path: '/site/:id',      redirect: to => `/site/${to.params.id}/editor` },
    { path: '/site/:id/editor',  component: SiteEditorPage },
    { path: '/site/:id/config',  component: SiteConfigPage },
]
```

#### 步骤 6.3 SiteEditorPage 布局

```
┌────────────────────────────────────────────────────────────────┐
│  导航栏：[站点名] [状态chip] [启动/停止] [配置 ⚙] [站点管理]  │
├──────────────────┬──────────────────┬──────────────────────────┤
│  💬 对话区        │  🖥 实时预览      │  📋 需求/流水线 侧边栏   │
│  ConversationPanel│  SitePreview     │  RequirementsPanel       │
│                  │  (iframe)        │  PipelinePanel           │
│  [消息历史]      │                  │                          │
│  [输入框][发送]  │  [TaskLogPane]   │                          │
│                  │  (实时日志)      │                          │
└──────────────────┴──────────────────┴──────────────────────────┘
```

**注意**：现有 Jinja2 模板保留（`/legacy/*`），SPA 作为新入口逐步接管

**预期产物**：
- Vite + Vue3 + TypeScript 项目骨架
- 4个页面 + 全部业务组件
- Pinia stores + composables
- vite.config.ts API 代理

---

## 关键文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `main_service/app/main.py` | 重构 | 拆分为 8 个模块，保留路由注册 |
| `main_service/app/db.py` | 新建 | Schema v2，WAL，索引 |
| `main_service/app/ws.py` | 新建 | WebSocket 连接管理器 |
| `main_service/app/conversations.py` | 新建 | 多轮对话逻辑 |
| `main_service/app/requirements_mgr.py` | 新建 | 需求事件归档 |
| `main_service/app/pipelines.py` | 新建 | 流水线调度器 |
| `main_service/Dockerfile` | 修改 | 增加 Node.js 构建步骤 |
| `main_service/frontend/` | 新建 | Vue3 + Vite SPA |
| `docker-compose.yml` | 可选修改 | 如需独立前端构建步骤 |

---

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| WebSocket 单进程限制 | 单进程部署，REST 接口保留作降级 |
| LLM 需求归档频率过高 | 每 5 次事件触发一次，支持手动触发 |
| 流水线中途服务重启 | startup() 中检测 running pipeline，标记为 failed + 恢复策略说明 |
| SPA 重构工作量大 | 渐进式：先建骨架+路由，逐页面迁移，Jinja2 模板保留兜底 |
| Gemini 不可用 | 前端由 Claude 主导，Codex 负责后端 |

---

## 阶段优先级与工期估算

| 阶段 | 优先级 | 估算 | 负责方 |
|------|--------|------|--------|
| 阶段一：DB + 模块拆分 | P0 | 1-2天 | Codex |
| 阶段二：WebSocket 实时日志 | P0 | 1天 | Codex + Claude |
| 阶段三：AI 多轮对话 | P1 | 2-3天 | Codex + Claude |
| 阶段四：需求自动归档 | P1 | 1-2天 | Codex + Claude |
| 阶段五：流水线编排 | P1 | 2天 | Codex |
| 阶段六：前端 SPA 重构 | P2 | 3-5天 | Claude |

**总计：约 10-13 天**（按阶段并行推进可压缩）

---

## SESSION_ID（供 /ccg:execute 使用）

- CODEX_SESSION: 019cffff-a466-7313-a3d3-0caf2e26c4e4
- GEMINI_SESSION: N/A（认证不可用）
