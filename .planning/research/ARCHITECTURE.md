# Architecture Evolution Research

**Date:** 2026-04-23

## Executive Summary

本文档分析 NextProject 平台从单站点模型演进到多仓库项目模型、AI 编码代理编排、半自动测试生成与执行、以及可扩展 Skill 部署系统所需的架构变更。所有新组件建立在现有 FastAPI + Celery + WebSocket + Site 基础之上，采用增量演进策略。

---

## 1. Multi-Repo Project Model

### 现状

当前 `Site` 是最顶层实体。每个 Site 对应一个 `generated_sites/<site_id>/` 目录，内含单个 git 仓库。Task、Conversation、WorkflowRun、DeployConfig 全部挂在 `site_id` 下。没有"项目"概念——一个 Site 就是一个独立应用。

### 目标

一个 **Project** 包含多个 **Repo**（微服务、前端、后端、共享库等），支持跨仓库的需求拆解、统一部署、统一测试。

### 新数据模型

```
Project (新)
├── id, name, owner_id, org_id, description, status
├── created_at, updated_at
│
├── ProjectRepo (新, 1:N)
│   ├── id, project_id (FK), name, repo_type (frontend/backend/service/shared)
│   ├── git_url (远程仓库地址, 可空)
│   ├── local_path (磁盘路径, 指向 generated_sites/<project_id>/<repo_name>/)
│   ├── default_branch, language, framework
│   ├── build_config_json (Dockerfile path, build context, port)
│   └── created_at, updated_at
│
├── Site (改造: 添加 project_id FK, 可空)
│   └── 保留向后兼容：project_id=NULL 时行为与现在相同
│
├── WorkflowRun (改造: 添加 project_id FK, 可空)
│   └── 支持项目级别的工作流
│
└── AgentTask (改造: 添加 project_id, repo_id FK, 可空)
    └── 任务可以指定在哪个 repo 下执行
```

### 文件系统布局

```
generated_sites/
├── <site_id>/                  # 兼容旧模式（单站点）
│   ├── backend/
│   ├── frontend/
│   └── docs/
│
└── projects/
    └── <project_id>/
        ├── .np/                # 项目级元数据
        │   ├── project.json
        │   └── workflows/
        ├── api-service/        # ProjectRepo, 独立 git repo
        │   ├── .git/
        │   ├── src/
        │   └── Dockerfile
        ├── web-frontend/       # ProjectRepo
        │   ├── .git/
        │   └── src/
        └── docker-compose.yml  # 项目级编排（生成）
```

### 组件边界

| 组件 | 职责 | 通信方向 |
|------|------|----------|
| `ProjectService` (新) | 项目 CRUD、仓库注册、项目级操作 | ← API routes → DB |
| `ProjectRepoService` (新) | 仓库克隆、初始化、文件操作 | ← ProjectService → filesystem, git |
| `SiteService` (改造) | 保留现有逻辑，新增 `project_id` 感知 | ← API routes → DB, filesystem |
| `TaskService` (改造) | 任务创建时支持 `repo_id`，cwd 指向对应 repo | ← API routes → Celery |

### 数据流

```
用户创建项目
  → POST /api/v2/projects
    → ProjectService.create_project()
      → DB: 插入 Project 行
      → filesystem: 创建 projects/<project_id>/ 目录

用户添加仓库
  → POST /api/v2/projects/{id}/repos
    → ProjectRepoService.add_repo()
      → git clone / git init 到 projects/<project_id>/<repo_name>/
      → DB: 插入 ProjectRepo 行

用户导入已有 git 仓库
  → POST /api/v2/projects/{id}/repos/import
    → ProjectRepoService.import_repo()
      → git clone <url> → projects/<project_id>/<repo_name>/
      → 自动检测 language, framework, Dockerfile
```

---

## 2. AI Coding Agent Orchestration

### 现状

`TaskService.run_develop_task()` 直接调用 Claude Code CLI 或 Codex CLI 作为子进程。用户 API Key 从 `UserLLMProvider` 表查询，注入环境变量。支持 provider failover（claude_code → codex → gemini_cli）。单任务 = 单 CLI 调用，prompt 一次传入。

### 目标

- 需求自动拆解为子任务（跨 repo）
- 对话式编码（多轮交互，不是一次性 prompt）
- 用户自带 API Key，加密存储
- 任务进度实时推送

### 架构设计

#### 2.1 Task Decomposition Engine

```
RequirementDecomposer (新 Service)
│
├── 输入: 用户自然语言需求 + Project 上下文
├── 调用: LLM API（用户的 Key）进行需求分析
├── 输出: SubTask 列表，每个 SubTask 绑定一个 repo_id
│
└── SubTask (新模型或复用 AgentTask)
    ├── parent_task_id (可空, FK → AgentTask)
    ├── repo_id (FK → ProjectRepo)
    ├── sequence (执行顺序)
    ├── dependency_ids (JSON, 依赖的其他子任务)
    ├── prompt (拆解后的具体指令)
    └── status
```

**数据流：**

```
用户提交需求
  → POST /api/v2/projects/{id}/tasks  (payload: {prompt, provider, ...})
    → TaskService.create_project_task()
      → RequirementDecomposer.decompose(prompt, project_context)
        → LLM API call (使用用户 Key)
        → 返回 [{repo: "api-service", prompt: "..."}, {repo: "web-frontend", prompt: "..."}]
      → 为每个子任务创建 AgentTask (parent_task_id 指向主任务)
      → 按 dependency 顺序 enqueue 到 Celery
        → Celery worker 执行 CLI 调用
        → WebSocket 实时推送每个子任务日志
      → 所有子任务完成 → 主任务标记 SUCCESS
```

#### 2.2 Conversational Coding

现有 `Conversation` + `ConversationMessage` 模型已经支持多轮对话。需要增强：

```
ConversationService (改造)
│
├── 用户发送消息
│   → 构建上下文（历史消息 + 项目文件 + 当前 diff）
│   → 调用 Claude Code CLI (--conversation 模式) 或 API
│   → 流式返回 AI 回复 → WebSocket 推送
│   → AI 回复中包含代码修改 → 自动 apply 到对应 repo
│
└── 每次修改后
    → git commit (自动)
    → 可选: 触发增量测试
```

#### 2.3 API Key 管理

现有 `UserLLMProvider` 已存储 `api_key`。需要增强：

- **加密存储**: `api_key` 使用 AES-256 加密后存入 DB，运行时解密
- **连通性验证**: `POST /api/v2/providers/{id}/verify` → 调用对应 API 的 models.list 端点
- **用量追踪**: 可选字段记录每次 token 消耗

```
UserLLMProvider (改造)
├── api_key_encrypted (替代明文 api_key)
├── verified_at (最近验证时间)
├── last_used_at
└── total_tokens_used (可选)
```

#### 2.4 组件边界

| 组件 | 职责 | 通信 |
|------|------|------|
| `RequirementDecomposer` (新) | 用 LLM 拆解需求为子任务 | → LLM API (用户 Key), ← TaskService |
| `AgentOrchestrator` (新) | 管理子任务依赖、顺序执行、失败重试 | → Celery, → WebSocket, ← TaskService |
| `TaskService` (改造) | 新增 `create_project_task()`, 支持 `repo_id` | → DB, → Celery |
| `ConversationService` (改造) | 对话式编码，流式响应 | → LLM CLI/API, → WebSocket |
| `ProviderService` (改造) | Key 加密、验证、解密 | → DB, → external API |

---

## 3. Semi-Automatic Playwright Test Generation & Execution

### 现状

- `smoke_test_task` 运行固定的 `playwright_smoke_runner.mjs` 脚本
- 测试在 `main_service` 容器内执行（已安装 Playwright + Chromium）
- 结果通过 TaskLog + WebSocket 推送
- 无测试用例管理、无 AI 生成测试的能力

### 目标

AI 编码完成后 → 自动生成 Playwright 测试用例草稿 → 用户可查看/修改 → 执行并报告结果。

### 新数据模型

```
TestSuite (新)
├── id, project_id / site_id, name, description
├── status (draft / ready / running / passed / failed)
├── created_at, updated_at

TestCase (新)
├── id, suite_id (FK), name, description
├── source (ai_generated / manual / imported)
├── code (Playwright test 代码, TypeScript/JS)
├── status (draft / approved / passed / failed / skipped)
├── last_run_at, last_result_json
├── ai_prompt (生成此用例时使用的 prompt, 便于重新生成)
├── created_at, updated_at

TestRun (新)
├── id, suite_id (FK), task_id (FK → AgentTask, 可空)
├── status (running / passed / failed)
├── summary_json (通过数/失败数/跳过数)
├── artifacts_dir (截图、视频、trace 存储路径)
├── started_at, finished_at

TestRunResult (新)
├── id, run_id (FK), test_case_id (FK)
├── status (passed / failed / skipped)
├── error_message, screenshot_path
├── duration_ms
```

### 数据流

```
AI 编码任务完成
  → TaskService 触发后置钩子
    → TestGenerationService.generate_tests(task, repo_context)
      → 构建 prompt: "根据以下代码变更生成 Playwright 测试用例: <git diff>"
      → LLM API call (用户 Key)
      → 解析返回的测试代码
      → 创建 TestSuite + TestCase (status=draft)
      → WebSocket 通知: "已生成 N 个测试用例草稿"

用户查看/修改测试用例
  → GET /api/v2/tests/suites/{id}/cases
  → PUT /api/v2/tests/cases/{id}  (修改代码或标记 approved)

用户执行测试
  → POST /api/v2/tests/suites/{id}/run
    → TestService.create_run()
      → 将 approved 的 TestCase 写入临时目录
      → 创建 AgentTask (task_type=test_playwright)
      → Celery worker:
        → 启动 Playwright (npx playwright test)
        → 流式日志 → WebSocket
        → 解析结果 → 更新 TestRunResult
        → 截图/视频存入 MinIO 或 artifacts 目录
      → WebSocket 通知最终结果
```

### 组件边界

| 组件 | 职责 | 通信 |
|------|------|------|
| `TestGenerationService` (新) | 调用 LLM 生成测试代码 | → LLM API, ← TaskService (hook) |
| `TestService` (新) | 测试用例 CRUD、执行调度 | → DB, → Celery, → WebSocket |
| `TestRunnerTask` (新 Celery task) | 实际执行 Playwright | → Playwright CLI, → filesystem |
| `TestArtifactService` (新) | 管理截图/视频/trace | → MinIO / filesystem |

---

## 4. Skill-Based Deployment System

### 现状

- `Skill` 模型已存在，支持 name/content/triggers，绑定到 Site
- `SkillService` 管理 CRUD 和 Site 绑定
- `DeployService` 非常简单：创建 deploy task，deploy_task Celery 任务只做 restart_site 或 Apollo 占位
- `SiteDeployConfig` 硬编码了 Apollo 特有字段（harbor_domain, login_tel 等）

### 目标

部署通过 **Skill 定义文件** 驱动：每个 Skill 定义一系列步骤（Step），每个步骤是一个可执行动作（HTTP 调用、Docker 命令、Shell 脚本等）。新增部署平台只需添加 Skill 文件。

### 设计

#### 4.1 DeploySkill 结构

Skill 的 `content` 字段存储 YAML/Markdown 格式的部署步骤定义：

```yaml
# deploy-skill: kubernetes
name: Kubernetes 部署
description: 通过 K8s API 部署应用
triggers: [deploy]

variables:
  - name: KUBECONFIG
    description: K8s 配置文件路径
    required: true
  - name: NAMESPACE
    description: 目标命名空间
    default: default
  - name: IMAGE_TAG
    description: 镜像标签
    default: latest

steps:
  - id: docker_build
    name: 构建 Docker 镜像
    type: shell
    command: docker build -t ${IMAGE_REGISTRY}/${APP_NAME}:${IMAGE_TAG} .
    working_dir: ${REPO_PATH}
    
  - id: docker_push
    name: 推送镜像
    type: shell
    command: docker push ${IMAGE_REGISTRY}/${APP_NAME}:${IMAGE_TAG}
    depends_on: [docker_build]
    
  - id: k8s_apply
    name: 更新 K8s Deployment
    type: http
    method: PATCH
    url: ${K8S_API}/apis/apps/v1/namespaces/${NAMESPACE}/deployments/${APP_NAME}
    headers:
      Authorization: Bearer ${K8S_TOKEN}
      Content-Type: application/strategic-merge-patch+json
    body: |
      {"spec":{"template":{"spec":{"containers":[{"name":"${APP_NAME}","image":"${IMAGE_REGISTRY}/${APP_NAME}:${IMAGE_TAG}"}]}}}}
    depends_on: [docker_push]
    
  - id: verify
    name: 验证部署
    type: http
    method: GET
    url: ${K8S_API}/apis/apps/v1/namespaces/${NAMESPACE}/deployments/${APP_NAME}
    headers:
      Authorization: Bearer ${K8S_TOKEN}
    success_condition: $.status.readyReplicas > 0
    depends_on: [k8s_apply]
    retry: { max: 5, delay: 10 }
```

#### 4.2 新数据模型

```
DeploySkill (Skill 的子类型, 通过 scope='deploy' 区分)
└── content 字段存储 YAML 步骤定义

DeployEnvironment (新)
├── id, project_id / site_id, name (如 "production", "staging")
├── skill_id (FK → Skill, 指定使用哪个部署 Skill)
├── variables_json (加密存储, 环境变量值)
├── created_at, updated_at

DeployRun (新, 或复用 AgentTask)
├── id, environment_id (FK), task_id (FK → AgentTask)
├── status (running / success / failed / rollback)
├── steps_status_json ({step_id: {status, output, started_at, finished_at}})
├── started_at, finished_at

# 多应用批量部署
DeployBatch (新)
├── id, project_id
├── environment_id (FK)
├── repo_ids_json (要部署的 repo 列表)
├── status, started_at, finished_at
```

#### 4.3 Skill 执行引擎

```
SkillExecutor (新)
├── parse_skill(content: str) → SkillDefinition
├── resolve_variables(definition, environment) → resolved steps
├── execute_step(step) → StepResult
│   ├── type=shell → subprocess.exec
│   ├── type=http → httpx.request
│   ├── type=docker → docker CLI
│   └── type=custom → 调用注册的自定义 handler
├── execute_skill(definition, environment) → 按依赖顺序执行 steps
└── 每个 step 的日志 → WebSocket 实时推送
```

#### 4.4 微服务批量部署

```
用户发起项目部署
  → POST /api/v2/projects/{id}/deploy
    → DeployService.create_batch_deploy(project, environment, repo_ids)
      → 对每个 repo:
        → 解析对应的 DeploySkill
        → 创建 AgentTask (task_type=deploy_skill)
        → 注入 repo 特定变量 (REPO_PATH, APP_NAME, PORT 等)
      → Celery worker 按依赖顺序执行
      → WebSocket 推送每个 repo 的部署进度
```

### 组件边界

| 组件 | 职责 | 通信 |
|------|------|------|
| `SkillExecutor` (新) | 解析 + 执行 Skill 步骤 | → subprocess, httpx, docker |
| `DeployService` (改造) | 部署编排、批量部署 | → SkillExecutor, → Celery, → DB |
| `DeployEnvironmentService` (新) | 环境变量管理（加密存储） | → DB |
| `SkillService` (改造) | 新增 deploy scope 支持 | → DB |

---

## 5. Integration with Existing Architecture

### 5.1 现有组件映射

```
┌─────────────────────────────────────────────────────────────────┐
│ Frontend (Vue 3)                                                │
│ ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────────┐  │
│ │ Project   │ │ Code     │ │ Test     │ │ Deploy            │  │
│ │ Manager   │ │ Editor   │ │ Runner   │ │ Dashboard         │  │
│ └─────┬─────┘ └────┬─────┘ └────┬─────┘ └────────┬──────────┘  │
│       │             │            │                 │             │
│       └─────────────┴────────────┴─────────────────┘             │
│                          │ Axios + WebSocket                     │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│ Nginx (frontend container)                                       │
│ /api/* → main-service:8080                                       │
│ /ws/*  → main-service:8080                                       │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│ FastAPI Backend (main-service)                                    │
│                                                                   │
│ ┌─────────────────────────────────────────────────────────────┐   │
│ │ API Layer (backend/api/v2/)                                 │   │
│ │ ┌──────────┐ ┌─────────┐ ┌──────────┐ ┌──────────────────┐│   │
│ │ │projects  │ │tasks    │ │tests     │ │deploy            ││   │
│ │ │  (新)    │ │(改造)   │ │  (新)    │ │  (改造)          ││   │
│ │ └────┬─────┘ └────┬────┘ └────┬─────┘ └───────┬──────────┘│   │
│ └──────┼────────────┼───────────┼────────────────┼───────────┘   │
│        │            │           │                │                │
│ ┌──────┼────────────┼───────────┼────────────────┼───────────┐   │
│ │ Service Layer (backend/services/)                           │   │
│ │ ┌──────────────┐ ┌──────────────────┐ ┌──────────────────┐│   │
│ │ │ProjectService│ │RequirementDecomp.│ │TestGeneration    ││   │
│ │ │   (新)       │ │     (新)         │ │Service (新)      ││   │
│ │ └──────┬───────┘ └────────┬─────────┘ └───────┬──────────┘│   │
│ │ ┌──────┴───────┐ ┌────────┴─────────┐ ┌───────┴──────────┐│   │
│ │ │ProjectRepo   │ │AgentOrchestrator │ │TestService       ││   │
│ │ │Service (新)  │ │     (新)         │ │   (新)           ││   │
│ │ └──────────────┘ └──────────────────┘ └──────────────────┘│   │
│ │ ┌──────────────┐ ┌──────────────────┐ ┌──────────────────┐│   │
│ │ │SkillExecutor │ │DeployEnvironment │ │SiteService       ││   │
│ │ │   (新)       │ │Service (新)      │ │  (现有,改造)     ││   │
│ │ └──────────────┘ └──────────────────┘ └──────────────────┘│   │
│ └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│ ┌────────────────────────────────────────────────────────────┐   │
│ │ Task Layer (backend/tasks/)                                │   │
│ │ develop_code (现有) │ deploy (改造) │ test (改造)          │   │
│ │ test_generate (新)  │ deploy_skill (新)                    │   │
│ └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
         │                        │                     │
         ▼                        ▼                     ▼
┌─────────────┐  ┌──────────────────────┐  ┌─────────────────────┐
│ Celery      │  │ PostgreSQL / SQLite   │  │ Redis               │
│ Workers     │  │ (数据持久化)          │  │ (broker + pub/sub)  │
│             │  └──────────────────────┘  └─────────────────────┘
│ ┌─────────┐ │
│ │Claude   │ │  ┌──────────────────────┐  ┌─────────────────────┐
│ │Code CLI │ │  │ MinIO                │  │ Prometheus/Grafana  │
│ ├─────────┤ │  │ (artifacts, 截图)    │  │ (监控)              │
│ │Codex    │ │  └──────────────────────┘  └─────────────────────┘
│ │CLI      │ │
│ ├─────────┤ │  ┌──────────────────────┐
│ │Playwright│ │  │ Codex MCP Bridge     │
│ │Chromium │ │  │ (现有)               │
│ └─────────┘ │  └──────────────────────┘
└─────────────┘
```

### 5.2 WebSocket 集成

现有 WebSocket 通道 (`/ws/tasks/{task_id}/logs`) 已经可以推送任务日志。新增：

| 通道 | 用途 |
|------|------|
| `/ws/tasks/{task_id}/logs` | 现有，不变 |
| `/ws/projects/{project_id}/events` | 新增，项目级事件（子任务状态变更、部署进度） |
| `/ws/tests/{run_id}/progress` | 新增，测试执行进度 |
| `/ws/deploy/{batch_id}/progress` | 新增，批量部署进度 |

所有新 WebSocket 通道复用现有 `websocket_manager.publish()` 机制，通过 Redis pub/sub 广播。

### 5.3 Task 系统扩展

现有 `SUPPORTED_TASK_TYPES`:
```python
{"develop_code", "test_local_playwright", "deploy_local", "deploy_apollo"}
```

新增:
```python
{
    "decompose_requirement",   # 需求拆解
    "develop_code",            # 保留
    "test_generate",           # AI 生成测试
    "test_playwright",         # 执行 Playwright 测试 (替代 test_local_playwright)
    "deploy_skill",            # Skill 驱动部署 (替代 deploy_local/deploy_apollo)
    "deploy_batch",            # 批量部署编排
}
```

### 5.4 API 路由规划

```
/api/v2/projects/                           # 项目 CRUD
/api/v2/projects/{id}/repos                  # 仓库管理
/api/v2/projects/{id}/repos/{repo_id}/files  # 仓库文件浏览
/api/v2/projects/{id}/tasks                  # 项目级任务
/api/v2/projects/{id}/deploy                 # 项目级部署

/api/v2/tests/suites                         # 测试套件
/api/v2/tests/suites/{id}/cases              # 测试用例
/api/v2/tests/suites/{id}/run                # 执行测试
/api/v2/tests/runs/{id}                      # 测试运行详情

/api/v2/deploy/environments                  # 部署环境管理
/api/v2/deploy/environments/{id}/variables   # 环境变量（加密）
/api/v2/deploy/runs/{id}                     # 部署运行详情

# 现有路由保留兼容
/api/v2/sites/         # 保留，独立站点模式
/api/v2/tasks/         # 保留，站点级任务
/api/v2/skills/        # 保留 + 扩展 deploy scope
```

---

## 6. Suggested Build Order

基于组件依赖关系，推荐以下构建顺序：

### Phase 1: Foundation — 多仓库项目模型

**优先级最高。所有后续功能都依赖"项目"作为顶层实体。**

1. **数据模型**: `Project`, `ProjectRepo` 模型 + Alembic 迁移
2. **Service**: `ProjectService`, `ProjectRepoService`
3. **API**: `/api/v2/projects/` CRUD 路由
4. **Site 改造**: `Site` 添加 `project_id` 可空 FK（向后兼容）
5. **前端**: 项目管理页面（创建、仓库列表、仓库文件浏览）
6. **文件系统**: `generated_sites/projects/` 目录结构

**完成标志**: 用户可以创建项目、添加/导入 git 仓库、浏览仓库文件。

### Phase 2: AI Agent 增强

**依赖 Phase 1 的项目/仓库模型。**

1. **API Key 加密**: `UserLLMProvider` 加密改造 + 验证端点
2. **TaskService 改造**: 支持 `repo_id` 参数，cwd 指向对应 repo
3. **RequirementDecomposer**: 需求拆解服务
4. **AgentOrchestrator**: 子任务编排（依赖、顺序执行、失败处理）
5. **ConversationService 增强**: 多轮对话 + 代码修改
6. **前端**: 需求输入 → 子任务展示 → 实时日志面板

**完成标志**: 用户描述需求 → AI 自动拆解 → 多 repo 并行/顺序编码 → 实时进度。

### Phase 3: 测试系统

**依赖 Phase 2 的 AI 编码能力（生成测试需要 LLM 调用）。**

1. **数据模型**: `TestSuite`, `TestCase`, `TestRun`, `TestRunResult`
2. **TestGenerationService**: AI 生成测试用例
3. **TestService**: 测试 CRUD + 执行调度
4. **Celery task**: `test_playwright` 任务
5. **后置钩子**: 编码任务完成 → 自动触发测试生成
6. **前端**: 测试用例编辑器、运行结果面板、截图查看

**完成标志**: AI 编码后自动生成测试草稿 → 用户审核 → 执行 → 查看结果。

### Phase 4: Skill 部署系统

**依赖 Phase 1 的项目模型 + Phase 3 的测试通过后触发部署。**

1. **SkillExecutor**: Skill YAML 解析 + 步骤执行引擎
2. **DeployEnvironment**: 环境变量加密管理
3. **DeployService 改造**: Skill 驱动部署替代硬编码逻辑
4. **批量部署**: 多 repo 并行部署
5. **内置 Skills**: Docker local、K8s、Apollo 三个预置 Skill
6. **前端**: 部署配置、Skill 编辑器、部署进度面板

**完成标志**: 用户选择 Skill + 配置环境 → 一键部署多服务 → 实时进度 → 结果验证。

### 依赖图

```
Phase 1 (Project Model)
  │
  ├──→ Phase 2 (AI Agent)
  │       │
  │       └──→ Phase 3 (Testing)
  │
  └──→ Phase 4 (Deployment)
              │
              └── Phase 3 可选前置（测试通过后触发部署）
```

Phase 2 和 Phase 4 可以一定程度并行开发（共享 Phase 1 基础），但 Phase 3 依赖 Phase 2 的 LLM 调用能力。Phase 4 的"测试通过后自动部署"功能需要 Phase 3 先完成。

---

## 7. Key Technical Decisions

| 决策 | 方案 | 理由 |
|------|------|------|
| 项目模型与 Site 关系 | Project 包含多个 Repo，Site 可选关联 Project | 向后兼容：现有单站点用户不受影响 |
| 需求拆解 | 服务端 LLM 调用（非 CLI） | CLI 模式只适合执行，拆解需要结构化 JSON 输出 |
| AI 编码执行 | 保留 CLI 子进程模式 | Claude Code CLI 和 Codex CLI 已验证可用，无需重写 |
| 测试存储 | DB 存代码 + MinIO 存 artifacts | 测试代码需要编辑，artifacts（截图/视频）适合对象存储 |
| Skill 定义格式 | YAML in Skill.content | 复用现有 Skill 模型，不需要额外存储层 |
| 部署变量加密 | AES-256-GCM, key 来自环境变量 | API Key 和部署凭证必须加密存储 |
| 子任务编排 | Celery chain/chord | 利用现有 Celery 基础设施，支持依赖和并行 |

---

## 8. Migration & Compatibility

### 数据库迁移策略

所有新表和 FK 使用 **可空字段**，确保现有数据无需迁移。

```python
# Site 表添加 project_id（Alembic 迁移）
op.add_column('sites', sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=True))

# AgentTask 表添加 project_id, repo_id
op.add_column('agent_tasks', sa.Column('project_id', sa.String(36), nullable=True))
op.add_column('agent_tasks', sa.Column('repo_id', sa.String(36), nullable=True))
```

### API 兼容

- 现有 `/api/v2/sites/*` 路由完全保留
- 现有 `/api/v2/tasks/*` 路由保留（`project_id`, `repo_id` 为可选参数）
- 新路由使用 `/api/v2/projects/*` 前缀

---

*Research completed: 2026-04-23*
