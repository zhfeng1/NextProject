# Research Summary: AI-Powered Development Platform

**Date:** 2026-04-23
**Sources:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md

---

## 1. Executive Summary

NextProject 正在从单站点 AI 编码工具演进为面向微服务架构的全栈 AI 开发平台。竞品分析（Replit、Bolt、Cursor、Copilot、Devin）表明，市场正在向"异步云端 Agent + 并行多 Agent"方向集体涌入，但所有竞品均基于单仓库模型，且在部署侧绑定自家基础设施。NextProject 的差异化空间在于：多仓库项目模型（天然支持微服务）、Skill 驱动的可扩展部署机制、以及介于全自动与无测试之间的半自动测试流程。

现有技术栈（FastAPI + Celery + WebSocket + Redis + PostgreSQL + Monaco + Playwright + MinIO）已具备支撑上述差异化功能所需的基础设施，新增依赖以最小化为原则：核心新增 `claude-agent-sdk`（替代手写 subprocess）、`python-on-whales`（Compose/Buildx 支持）、`GitPython`（仓库操作）。架构演进采用增量策略，通过可空外键保持向后兼容，现有单站点用户不受影响。

最大的工程风险集中在安全层（API Key 明文存储、命令注入、文件系统沙箱缺失）和模型迁移层（Site → Project + Repo），这两类问题必须在 Phase 1 和 Phase 2 早期解决，否则会成为后续阶段的地雷。

---

## 2. Key Stack Decisions

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Claude Code 集成 | `claude-agent-sdk` 0.1.65 | 官方 SDK，原生流式事件，替代手写 subprocess；`claude-code-sdk` 已废弃 |
| Codex 集成 | `@openai/codex-sdk` 0.120.0 (Node.js) | Python SDK 实验性不可用；通过 subprocess 调 Node.js 脚本是唯一可靠路径 |
| Agent 抽象层 | 自建 `AgentDriver` Protocol | CLI subprocess 模式与 LangChain/CrewAI 的 LLM API chain 模型不匹配；现有路由逻辑抽象即可 |
| Docker 编程接口 | `python-on-whales` 0.81.0 | 唯一支持 Compose + Buildx 的方案；`docker-py` 不支持这两个核心需求 |
| Git 操作 | `GitPython` 3.1.47 | 容器内已有 git，薄封装即可；Dulwich 性能差，pygit2 安装复杂 |
| K8s 部署 | `kubernetes` 35.0.0 | 官方客户端，v1 不需要 Helm |
| Skill 定义格式 | YAML frontmatter + Markdown | 行业标准格式，复用现有 `Skill.content` 字段，无需额外存储层 |
| 异步子进程 | `anyio` (已有传递依赖) | FastAPI → Starlette → AnyIO，零额外安装 |
| API Key 加密 | `cryptography.fernet` (已有传递依赖) | `python-jose[cryptography]` 的传递依赖，Fernet 对称加密即可 |
| 前端终端渲染 | `@xterm/xterm` 6.0.0 | VS Code 同款，原生支持 ANSI 色码；旧 `xterm` 包已废弃 |
| Diff 展示 | Monaco 自带 Diff Editor | 已安装 Monaco，零额外依赖 |
| 测试执行报告 | `pytest-json-report` 1.5.0 | JSON 格式报告，便于解析和前端展示 |

**明确不引入：** LangChain、CrewAI、Helm SDK、Terraform/Pulumi、docker-py、Dulwich、`claude-code-sdk`（废弃）、Codex Python SDK（实验性）

---

## 3. Feature Priorities

### Table Stakes（必须有，否则不可上线）

| Feature | Description | 已有基础 |
|---------|-------------|----------|
| Natural Language → Code | 自然语言生成代码 | Celery + CLI 子进程 |
| Multi-file Editing | AI 一次修改多个文件 | Claude Code CLI 支持 |
| Task Plan → Execute | AI 先生成计划，确认后执行 | Task 系统已有 |
| Streaming Output | 实时日志推送 | WebSocket 已有 |
| Error Self-Healing Loop | AI 检测错误自动修复 | 待实现 |
| Multi-Model Support | Claude/GPT/Gemini 切换 | Provider 路由已有 |
| 一键预览部署 | 构建后提供预览 URL | Preview proxy 基础已有 |
| 测试执行与结果展示 | 平台内执行测试展示结果 | Playwright runner 已有 |
| 用户认证 + API Key 管理 | JWT + 自带 Key 存储 | 已有（加密待完善）|
| 项目创建与文件浏览 | Monaco 编辑器基础功能 | 已有 |

### Differentiators（竞争壁垒，NextProject 独有定位）

| Feature | Description | Competitive Edge |
|---------|-------------|-----------------|
| **多仓库项目模型** | 一个项目关联多个 git 仓库 | 所有竞品均为单仓库，无法原生支持微服务 |
| **Skill-based 可扩展发布** | YAML 定义部署流程，新平台添加 Skill 即可 | 竞品绑定单一平台（Vercel/Replit Hosting） |
| **半自动测试流程** | AI 生成草稿 → 用户审核 → 执行 | 竞品要么全自动要么无测试 |
| 异步云端 Agent | 任务异步执行，关掉浏览器也能继续 | Celery 架构天然支持，对标 Copilot Coding Agent |
| 微服务批量部署 | 多仓库一键部署所有服务 | 竞品主要面向单应用 |
| 项目级 AI 上下文 | AI 感知多仓库结构和服务边界 | 无直接竞品 |
| Docker 本地部署预览 | Compose 构建运行完整应用栈 | 比浏览器沙箱更接近真实生产环境 |

### Anti-Features（刻意不做）

| Feature | Reason |
|---------|--------|
| 完全自治 Agent（Devin 模式） | 任务完成率低，用户失去控制感 |
| 浏览器内 IDE（WebContainers） | 技术门槛极高且限制框架；已有 Monaco + 服务端执行 |
| 自建 Hosting/CDN | 不做云基础设施，用 Skill 对接已有平台 |
| GitHub/GitLab 深度集成 | v1 用平台自管 git |
| 团队协作 / 权限管理 | v1 单用户，多租户后续里程碑 |

---

## 4. Architecture Overview

### Build Order

```
Phase 1: 多仓库项目模型（所有后续功能的基础）
  ├── 数据模型: Project, ProjectRepo + Alembic 迁移
  ├── Service: ProjectService, ProjectRepoService
  ├── API: /api/v2/projects/ CRUD
  ├── Site 改造: 添加 project_id 可空 FK（向后兼容）
  └── 前端: 项目管理页面

Phase 2: AI Agent 增强（依赖 Phase 1）
  ├── API Key 加密改造 + 连通性验证端点
  ├── TaskService 改造: 支持 repo_id，cwd 指向对应 repo
  ├── RequirementDecomposer: 需求拆解服务
  ├── AgentOrchestrator: 子任务依赖编排（Celery chain/chord）
  └── 前端: 需求输入 → 子任务展示 → 实时日志面板

Phase 3: 半自动测试系统（依赖 Phase 2 的 LLM 调用能力）
  ├── 数据模型: TestSuite, TestCase, TestRun, TestRunResult
  ├── TestGenerationService: AI 生成测试草稿（编码完成后钩子触发）
  ├── TestService: CRUD + 执行调度
  ├── Celery task: test_playwright
  └── 前端: 测试用例编辑器、运行结果、截图查看

Phase 4: Skill 部署系统（依赖 Phase 1 项目模型）
  ├── SkillExecutor: YAML 解析 + 步骤执行引擎（shell/http/docker）
  ├── DeployEnvironment: 环境变量加密管理
  ├── DeployService 改造: Skill 驱动替代硬编码逻辑
  ├── 批量部署: 多 repo 并行部署
  └── 内置 Skills: Docker local、K8s、Apollo
```

依赖图：Phase 1 → Phase 2 → Phase 3；Phase 1 → Phase 4（Phase 4 的"测试通过后自动部署"需要 Phase 3 先完成）。Phase 2 和 Phase 4 可以一定程度并行。

### Component Boundaries

| Component | Responsibility | Communication |
|-----------|---------------|---------------|
| `ProjectService` (新) | 项目 CRUD、仓库注册 | ← API routes → DB |
| `ProjectRepoService` (新) | 仓库克隆/初始化/文件操作 | ← ProjectService → filesystem, git |
| `RequirementDecomposer` (新) | LLM 拆解需求为子任务 | → LLM API (用户 Key) |
| `AgentOrchestrator` (新) | 子任务依赖、顺序、失败重试 | → Celery, → WebSocket |
| `TestGenerationService` (新) | 调用 LLM 生成测试代码 | → LLM API, ← TaskService hook |
| `TestService` (新) | 测试 CRUD + 执行调度 | → DB, → Celery, → WebSocket |
| `SkillExecutor` (新) | 解析 + 执行 Skill 步骤 | → subprocess, httpx, docker |
| `DeployEnvironmentService` (新) | 环境变量加密管理 | → DB |
| `SiteService` (改造) | 保留现有逻辑，新增 project_id 感知 | 不变 |
| `TaskService` (改造) | 支持 repo_id 参数 | 扩展 |

### New WebSocket Channels

| Channel | Purpose |
|---------|---------|
| `/ws/tasks/{task_id}/logs` | 现有，不变 |
| `/ws/projects/{project_id}/events` | 新增，项目级事件（子任务状态、部署进度） |
| `/ws/tests/{run_id}/progress` | 新增，测试执行进度 |
| `/ws/deploy/{batch_id}/progress` | 新增，批量部署进度 |

---

## 5. Critical Pitfalls

### Pitfall 1: API Key / 凭据明文存储（Phase 1，立即修复）

**风险：** `UserLLMProvider.api_key` 和 `SiteDeployConfig.login_password` 均为明文 Text 列。数据库备份或任何有 DB 读权限的人可直接获取所有用户凭据。

**Prevention:**
- 使用 `cryptography.fernet.Fernet` 加密存储，密钥从环境变量读取（库已作为传递依赖存在，零额外安装）
- API 返回时对 key/password 脱敏处理（只返回 `****last4`）
- API Key 通过临时文件传入子进程，任务结束后删除，不经过进程环境变量

### Pitfall 2: 文件系统沙箱缺失（Phase 1 加固，Phase 3 完整方案）

**风险：** AI Agent 在 `generated_sites/<site_id>/` 执行，Codex 使用了 `--dangerously-bypass-approvals-and-sandbox`，可读取 `../` 其他站点文件、容器环境变量、通过已挂载的 `docker.sock` 操控宿主机。

**Prevention:**
- 短期：至少移除 Celery worker 容器的 `docker.sock` 挂载
- 中期：每个 AI 任务在动态创建的独立容器中执行，只挂载对应仓库目录
- 每个 site 实现基于 Redis 的分布式锁，防止并发任务修改同一仓库产生 Git 冲突

### Pitfall 3: Site → Project 模型迁移风险（Phase 2）

**风险：** 所有功能（任务、部署、文件浏览）耦合在 `site_id` + 单目录结构上。引入 Project 概念需要同时改动模型、所有 API 路由、前端所有 store 和组件，一次性改动极易引入回归。

**Prevention:**
- API 版本化：新功能用 `/api/v2/projects/`，保留 `/api/v2/sites/` 完全不变
- 数据库迁移分两步：先加新表和可空 FK，再写 data migration 把现有 Site 转换为"单 repo project"
- 绝不在一次 PR 中同时改模型、API、前端——拆成 3 个独立 PR
- 每次迁移前 `pg_dump` 备份，大型迁移拆成多个小迁移，不盲目使用 `autogenerate`

### Pitfall 4: Playwright 资源消耗与 Flaky Test 循环（Phase 3）

**风险：** Chromium 每实例消耗 200-500MB，4 并发测试消耗 2GB+，易触发 OOM Kill。AI 生成的 flaky 测试会导致"修代码 → 测试失败 → 再修"的无限循环，每轮消耗 API tokens。

**Prevention:**
- 为测试任务设置独立 Celery queue，并发数限制为 1-2；`shm_size: '2gb'` + `--disable-dev-shm-usage`
- 生成测试的 prompt 中明确要求使用 `waitForSelector`、`waitForLoadState` 等 best practices
- 自动化测试设置最大重试上限（3 次），超过后标记"需人工检查"，不继续 AI 修复
- artifacts（截图/视频）上传 MinIO，Celery Beat 定期清理本地过期文件

### Pitfall 5: 部署步骤缺乏幂等性与 Rollback 能力（Phase 4）

**风险：** 部署任务中途失败重试时，可能导致同一 Deployment 被创建两次（副本数翻倍），或 token 过期引发级联失败。部署后无回滚能力，用户只能手动操作目标平台。

**Prevention:**
- 每个 Skill step 设计为幂等操作：`get-or-create` 模式，先查再创建
- 实现部署状态机：每步完成后持久化进度，重试时从上次失败步骤开始（不重做已完成步骤）
- Skill 定义增加 `rollback_steps` 字段，部署前记录"上一个已知良好版本"（镜像 tag / git commit）
- 实现一键 rollback API

---

## 6. Recommendations for Roadmap

### Immediate Actions（开始编码前必须决策）

1. **确认数据模型设计**：`Project` → `ProjectRepo` → `Site`（可空关联）的层次结构，以及 AI 任务的 `cwd` 定向到具体 `repo_id` 的 payload 格式。先设计 ERD 和 API schema，再写代码。

2. **安全优先级提升**：将 API Key 加密、凭据加密、`docker.sock` 挂载移除列为 Phase 1 的阻断项（not nice-to-have）。多用户场景下，任何一个安全漏洞都是平台级风险。

3. **锁定测试环境使用 PostgreSQL**：将 `SQLITE_JSON` 替换为 SQLAlchemy 跨数据库 `JSON` 类型，测试 docker-compose 连接 postgres 而非 sqlite，在 Phase 1 完成前修复，避免测试通过但生产出错。

### Phase Sequencing Recommendations

- **Phase 1（项目模型）** 是全局依赖，不可跳过或并行，估计是工程量最大的阶段（模型 + 迁移 + 向后兼容 + 前端）
- **Phase 2（AI Agent）** 和 **Phase 4（部署）** 可以在 Phase 1 完成后并行开发，但 Phase 4 的"测试通过触发部署"集成功能需等 Phase 3 完成
- **Phase 3（测试）** 可以从简单版本开始：先做"用户手动触发 AI 生成测试草稿 + 执行"，再做"编码完成自动触发"
- Provider Failover 的静默切换 bug（使用平台全局 Key 而非用户 Key）应在 Phase 1 的 AI 任务流程改造中顺带修复

### Differentiation Investment Priority

```
高优先级（核心竞争壁垒，早期建立）
  ├── 多仓库项目模型 → Phase 1，必须先做
  └── Skill-based 部署 → Phase 4，是长期平台护城河

中优先级（差异化但可迭代）
  └── 半自动测试流程 → Phase 3，可从 MVP 版本开始

低优先级（好用但非独特）
  ├── 成本感知（token 消耗展示）
  ├── Session Memory / 持久化上下文
  └── 结构化日志（structlog，P2 依赖，核心功能完成后引入）
```

### Risk Mitigation Summary

| Risk | Mitigation |
|------|-----------|
| API Key 安全 | Phase 1 强制加密，阻断项 |
| 模型迁移破坏现有功能 | 可空 FK + API 版本化 + 分 PR 拆分 |
| AI 任务费用失控 | token 上限参数 + 用户确认机制 |
| Playwright OOM | 独立 queue + 并发限制 |
| Skill 内容注入 | 导入审查 + prompt delimiter 隔离 |
| Git 并发冲突 | Redis 分布式锁 per repo |
| Celery 事件循环 | 锁定 `--pool=prefork`，注释标记约束 |

---

*Summary compiled: 2026-04-23*
*Based on: STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md*
