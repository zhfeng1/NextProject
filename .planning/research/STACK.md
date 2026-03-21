# Stack Research: AI-Powered Development Platform

**Research Date:** 2026-04-23

## Scope

本文档聚焦于 **超出现有技术栈** 的新增依赖和升级建议。现有栈（FastAPI, Vue 3, Celery, Redis, PostgreSQL, Docker Compose, Monaco, Playwright, MinIO, Prometheus/Grafana）已验证可用，此处不重复讨论，除非需要版本升级或替换。

---

## 1. AI Agent 编排层

### 1.1 Claude Code 集成

| 属性 | 值 |
|------|-----|
| **推荐** | `claude-agent-sdk` 0.1.65 |
| **安装** | `pip install claude-agent-sdk` |
| **Python** | >=3.10 |
| **许可证** | MIT |
| **置信度** | **高** — Anthropic 官方发布，已替代废弃的 `claude-code-sdk` |

**为什么用它：**
- 官方 Python SDK，直接在 Celery worker 中调用 Claude Code 能力
- 自带 Claude Code CLI，无需单独安装
- 支持流式事件（`async for message in query(prompt=...)`），可直接对接现有 WebSocket 日志推送
- 支持结构化输出（传入 JSON Schema）
- 取代当前 `codex_mcp/` 中手动 subprocess 管理的 Claude 集成模式

**用法示例：**
```python
from claude_agent_sdk import query

async def run_claude_task(prompt: str, working_dir: str):
    async for event in query(
        prompt=prompt,
        options={"cwd": working_dir}
    ):
        yield event  # 转发到 WebSocket
```

**不要用：**
- ~~`claude-code-sdk`~~ — 已废弃（2025-09 停更），勿使用
- ~~直接 `subprocess.Popen(["claude", ...])`~~ — SDK 已封装子进程管理、token 流式输出、会话持久化，手写 subprocess 无意义

**对现有代码的影响：**
- `codex_mcp/app/server.py` 中的 MCP bridge 可以简化或移除 Claude 相关的 subprocess 管理
- `backend/tasks/develop_code.py` 中 `task_service.run_develop_task()` 应改用 SDK 的异步 API
- `UserLLMProvider` 模型中存储的 Anthropic API Key 通过环境变量注入 SDK

### 1.2 OpenAI Codex CLI 集成

| 属性 | 值 |
|------|-----|
| **推荐（CLI）** | `@openai/codex` ~0.122.x (npm) |
| **推荐（SDK）** | `@openai/codex-sdk` 0.120.0 (npm, TypeScript) |
| **Node.js** | >=18 |
| **许可证** | Apache-2.0 |
| **置信度** | **高** — OpenAI 官方，活跃开发（709 releases, 75.6K stars） |

**为什么用它：**
- TypeScript SDK 通过 JSONL over stdin/stdout 与 CLI 通信，结构化事件流
- 支持 Thread 模型（多轮对话）、流式事件、结构化输出
- 已在 `main_service/Dockerfile` 中安装 `@openai/codex`，SDK 是上层封装

**当前状态 vs 升级路径：**
- 现有：`main_service/Dockerfile` 已安装 `@openai/codex`，Codex MCP bridge 通过 `codex mcp-server` 启动
- 升级：在 Python 侧通过 subprocess 调用 `@openai/codex-sdk`，或在 Node.js worker 中使用 TypeScript SDK
- Codex 的 Python SDK 目前是实验性的（需要本地 checkout），**不推荐生产使用**

**推荐集成策略：**
```
Celery Worker (Python)
  → subprocess 调用 node script
    → @openai/codex-sdk (TypeScript)
      → 结构化事件 → stdout → Python 解析 → WebSocket
```

**不要用：**
- ~~Codex Python SDK~~ — 实验性，需要本地 codex 仓库 checkout，不适合容器化部署

### 1.3 Agent 抽象层（自建）

| 属性 | 值 |
|------|-----|
| **推荐** | 自建 `AgentDriver` 抽象接口 |
| **置信度** | **高** — 项目已有 `SUPPORTED_PROVIDERS = {"codex", "claude_code", "gemini_cli"}` |

**为什么自建而不用框架：**
- LangChain/CrewAI 等框架增加复杂度，且本项目的 agent 调用模式是"CLI subprocess + 流式输出"，不是 LLM API chain
- 现有 `task_service.py` 已有 provider 路由逻辑，只需抽象为接口

**接口设计：**
```python
class AgentDriver(Protocol):
    async def execute(
        self,
        prompt: str,
        working_dir: Path,
        api_key: str,
        on_event: Callable[[AgentEvent], Awaitable[None]],
    ) -> AgentResult: ...
```

实现：`ClaudeDriver`（用 claude-agent-sdk）、`CodexDriver`（用 subprocess + codex-sdk）、`GeminiDriver`（用 subprocess + gemini-cli）

---

## 2. 多仓库项目管理

### 2.1 Git 操作库

| 属性 | 值 |
|------|-----|
| **推荐** | `GitPython` 3.1.47 |
| **安装** | `pip install GitPython` |
| **许可证** | BSD-3 |
| **置信度** | **中高** — 成熟稳定，但需注意资源泄漏 |

**为什么选 GitPython：**
- 现有系统已依赖 git CLI（`main_service/Dockerfile` 安装了 git），GitPython 是 git CLI 的薄封装
- 高层 API 覆盖 clone/pull/push/branch/commit/diff 等常用操作
- 比 Dulwich（纯 Python）快，因为底层调用原生 git

**注意事项：**
- GitPython 在长时间运行的进程中会泄漏文件句柄，Celery worker 中使用时必须显式 `repo.close()` 或用 `with` 上下文管理器
- 不适合 daemon 进程 — 但 Celery worker 是短任务模式，可接受

**不要用：**
- ~~Dulwich 1.1.0~~ — 纯 Python 实现，无需 git 安装，但性能差且 API 刚到 1.x（不稳定）。我们的容器里已有 git，没必要用纯 Python 方案
- ~~pygit2~~ — libgit2 绑定，安装复杂（需编译 C 库），Docker 镜像体积增加显著

### 2.2 项目-仓库数据模型（自建）

| 属性 | 值 |
|------|-----|
| **推荐** | 新增 `Project` 和 `Repository` SQLAlchemy 模型 |
| **置信度** | **高** — 纯数据建模，无外部依赖 |

**模型关系：**
```
User → Project (1:N)
Project → Repository (1:N)
Repository → Site (1:1, optional)  # 一个仓库可关联一个 Site 运行时
Project → Task (1:N)  # 任务绑定到项目级别
```

现有 `Site` 模型可保持不变，通过外键关联到 `Repository`。

---

## 3. 容器与部署管理

### 3.1 Docker 编程接口

| 属性 | 值 |
|------|-----|
| **推荐** | `python-on-whales` 0.81.0 |
| **安装** | `pip install python-on-whales` |
| **许可证** | MIT |
| **置信度** | **高** — Docker 官方博客推荐，活跃维护 |

**为什么选它而不是 docker-py：**
- `python-on-whales` 是 Docker CLI 的 1:1 映射，支持 `docker compose`、Buildx/BuildKit、多阶段构建
- `docker` (docker-py) 7.1.0 是 Docker Engine API 的 Python 重实现，不支持 Compose 和 Buildx
- 项目需要 `docker compose up/down/build`（本地部署预览）和 `docker build/push`（镜像发布），`python-on-whales` 天然支持
- 线程安全，无中间状态，适合 Celery worker 并发调用

**用法示例：**
```python
from python_on_whales import DockerClient

docker = DockerClient(compose_files=["./docker-compose.yml"])
docker.compose.up(services=["frontend", "backend"], detach=True, build=True)
docker.image.build(".", tags=["myapp:latest"])
docker.image.push("registry.example.com/myapp:latest")
```

**不要用：**
- ~~`docker` (docker-py) 7.1.0~~ — 不支持 Compose 和 Buildx，这两个是核心需求
- ~~直接 `subprocess.run(["docker", ...])`~~ — 缺乏类型安全、错误处理、返回值解析

### 3.2 Kubernetes 客户端

| 属性 | 值 |
|------|-----|
| **推荐** | `kubernetes` 35.0.0 |
| **安装** | `pip install kubernetes` |
| **许可证** | Apache-2.0 |
| **置信度** | **高** — 官方客户端，与 K8s API 版本同步 |

**为什么需要：**
- Skill 机制中的 K8s 部署需要创建 Deployment、Service、ConfigMap 等资源
- 官方客户端支持所有 K8s API，自动生成自 OpenAPI spec
- 支持 kubeconfig 和 in-cluster 配置

**用法场景：**
- 在 `deploy_service.py` 或 Skill executor 中，根据用户配置的 kubeconfig/token 创建 K8s 资源
- 不需要 Helm — v1 直接用 Kubernetes API 即可

**不要用：**
- ~~`kr8s`~~ — 第三方轻量客户端，API 覆盖不全
- ~~`kopf`~~ — Operator 框架，本项目不需要写 K8s Operator
- ~~Helm SDK~~ — v1 不需要 Chart 管理，直接 API 调用更简单

### 3.3 容器镜像 Registry 交互

| 属性 | 值 |
|------|-----|
| **推荐** | 通过 `python-on-whales` 的 `docker.image.push/pull` + `docker.login` |
| **置信度** | **高** — 复用已有依赖 |

**为什么不额外引入 skopeo：**
- `python-on-whales` 已支持 `docker login`、`docker push`、`docker pull`
- 项目场景是"构建→推送到用户指定 Registry"，不需要 registry-to-registry 直传
- 减少容器镜像中的工具安装

---

## 4. 浏览器测试增强

### 4.1 Playwright Python 升级

| 属性 | 值 |
|------|-----|
| **当前** | Playwright 1.58.2（frontend package.json + main_service） |
| **推荐** | `playwright` 1.58.0 (Python) + `pytest-playwright` 0.7.2 |
| **安装** | `pip install playwright pytest-playwright` |
| **置信度** | **高** — 与现有版本兼容 |

**为什么补充 Python 版：**
- 现有 `main_service/app/scripts/playwright_smoke_runner.mjs` 是 Node.js 脚本
- AI 生成的测试用例是 Python 代码（与后端技术栈一致），需要 Python Playwright
- `pytest-playwright` 提供 `page` fixture，简化测试编写
- Celery worker 中执行 Python 测试比调用 Node.js 脚本更自然

**测试生成与执行流程：**
```
AI Agent 生成 Python 测试代码
  → 写入 generated_sites/<id>/tests/
    → Celery worker 执行 pytest --playwright
      → 结果流式推送 WebSocket
```

### 4.2 测试结果解析

| 属性 | 值 |
|------|-----|
| **推荐** | 自建解析，基于 pytest 的 JSON/JUnit XML 输出 |
| **置信度** | **高** — pytest 内置 `--junitxml` 和 `--json-report`（via `pytest-json-report`） |

补充依赖：
- `pytest-json-report` 1.5.0 — 生成 JSON 格式测试报告
- `pytest-html` 4.1.1 — 可选，生成 HTML 报告供用户浏览器查看

---

## 5. 前端补充

### 5.1 终端组件（AI 输出展示）

| 属性 | 值 |
|------|-----|
| **推荐** | `@xterm/xterm` 6.0.0 |
| **安装** | `npm install @xterm/xterm @xterm/addon-fit @xterm/addon-web-links` |
| **许可证** | MIT |
| **置信度** | **中高** — VS Code 使用的终端组件，成熟稳定 |

**为什么需要：**
- AI agent 的输出是带 ANSI 色码的终端流，现有 WebSocket 日志查看器可能只是纯文本
- xterm.js 原生支持 ANSI escape 序列、链接、GPU 加速渲染
- 适合展示 `claude-agent-sdk` 和 `codex-sdk` 的流式输出

**注意：** 旧的 `xterm` npm 包已废弃，必须用 `@xterm/xterm` 新作用域包

### 5.2 Diff 展示

| 属性 | 值 |
|------|-----|
| **推荐** | Monaco Editor 自带 Diff Editor |
| **置信度** | **高** — 已安装 Monaco，零额外依赖 |

现有 `CodeEditor.vue` 中已集成 Monaco，直接使用 `monaco.editor.createDiffEditor()` 即可展示 AI 代码修改的 diff 视图。

---

## 6. Skill 执行引擎

### 6.1 YAML 驱动的 Skill 定义

| 属性 | 值 |
|------|-----|
| **推荐** | `PyYAML` 6.0.2 + `jsonschema` 4.23.0（验证） |
| **安装** | `pip install PyYAML jsonschema` |
| **置信度** | **高** — 行业标准 |

**为什么 YAML：**
- 2025/2026 行业标准是 YAML frontmatter + Markdown body（SKILL.md 格式）
- 现有 `Skill` 模型已有 `content`（Markdown）字段，只需补充 YAML frontmatter 解析
- 部署 Skill 的步骤化定义（获取 token → 获取命名空间 → 推镜像 → API 部署）用 YAML 步骤列表自然表达

**Skill YAML 格式示例：**
```yaml
name: deploy-k8s
description: 部署到 Kubernetes 集群
steps:
  - action: docker_build
    params:
      context: "."
      tag: "{{registry}}/{{app_name}}:{{version}}"
  - action: docker_push
    params:
      image: "{{registry}}/{{app_name}}:{{version}}"
  - action: k8s_apply
    params:
      manifest: deployment.yaml
      namespace: "{{namespace}}"
variables:
  - name: registry
    required: true
  - name: namespace
    default: default
```

**不要用：**
- ~~pypyr~~ — 完整的 YAML 流水线引擎，过重，且引入自己的执行模型
- ~~Kestra~~ — 服务端编排引擎，需要独立部署 Java 服务，不适合嵌入

---

## 7. 后端基础设施补充

### 7.1 异步子进程管理

| 属性 | 值 |
|------|-----|
| **推荐** | `anyio` 4.13.0（已是 FastAPI 传递依赖） |
| **置信度** | **高** — 零额外安装 |

**为什么：**
- `anyio.open_process()` 提供异步子进程管理，比 `asyncio.create_subprocess_exec` 更好的结构化并发
- 用于 Agent driver 中管理 Claude/Codex CLI 子进程的生命周期
- 已作为 FastAPI → Starlette → AnyIO 的传递依赖存在，无需额外安装

### 7.2 结构化日志

| 属性 | 值 |
|------|-----|
| **推荐** | `structlog` 25.5.0 |
| **安装** | `pip install structlog` |
| **许可证** | Apache-2.0 / MIT |
| **置信度** | **中** — 改善可观察性，但非阻塞需求 |

**为什么：**
- 现有系统日志来自 Uvicorn 默认输出，多 agent 并发执行时难以追踪
- structlog 支持 context variables（按 task_id/agent 绑定上下文），JSON 输出直接接入 Grafana Loki
- `fastapi-structlog` 包提供中间件集成

**优先级：低** — 核心功能完成后再引入

### 7.3 API Key 加密存储

| 属性 | 值 |
|------|-----|
| **推荐** | `cryptography` 44.0.3（已是 `python-jose[cryptography]` 的传递依赖） |
| **置信度** | **高** — 零额外安装 |

**为什么：**
- 用户 API Key 必须加密存储，不能明文入库
- `cryptography.fernet.Fernet` 提供对称加密，密钥从环境变量读取
- 已作为 `python-jose[cryptography]` 的传递依赖存在

---

## 8. 完整新增依赖汇总

### Python（追加到 `main_service/requirements.txt`）

| 包 | 版本 | 用途 | 优先级 |
|----|------|------|--------|
| `claude-agent-sdk` | 0.1.65 | Claude Code 集成 | **P0** |
| `python-on-whales` | 0.81.0 | Docker 编程接口 | **P0** |
| `GitPython` | 3.1.47 | Git 仓库操作 | **P0** |
| `kubernetes` | 35.0.0 | K8s 部署 API | **P1** |
| `PyYAML` | 6.0.2 | Skill YAML 解析 | **P1** |
| `jsonschema` | 4.23.0 | Skill 定义验证 | **P1** |
| `pytest-json-report` | 1.5.0 | 测试结果 JSON 输出 | **P1** |
| `structlog` | 25.5.0 | 结构化日志 | **P2** |

### Node.js（追加到 `main_service/package.json`）

| 包 | 版本 | 用途 | 优先级 |
|----|------|------|--------|
| `@openai/codex-sdk` | 0.120.0 | Codex 编程接口 | **P0** |

### 前端（追加到 `frontend/package.json`）

| 包 | 版本 | 用途 | 优先级 |
|----|------|------|--------|
| `@xterm/xterm` | 6.0.0 | 终端输出渲染 | **P1** |
| `@xterm/addon-fit` | 6.0.0 | 终端自适应尺寸 | **P1** |
| `@xterm/addon-web-links` | 6.0.0 | 终端链接可点击 | **P1** |

### 无需新增（已有或传递依赖）

| 能力 | 来源 |
|------|------|
| 异步子进程 (`anyio`) | FastAPI 传递依赖 |
| API Key 加密 (`cryptography`) | python-jose 传递依赖 |
| Diff 展示 | Monaco Editor 已有 |
| Playwright Python | 已在 main_service 镜像中 |
| YAML 解析 | PyYAML（Celery 传递依赖，但建议显式声明） |

---

## 9. 明确不推荐的技术

| 技术 | 原因 |
|------|------|
| **LangChain / LangGraph** | 本项目是 CLI agent 编排（subprocess + 流式输出），不是 LLM API chain。LangChain 增加抽象层但不解决核心问题 |
| **CrewAI** | 多 agent 框架，但 agent 定义模型与本项目的 CLI subprocess 模式不匹配 |
| **Helm SDK** | v1 不需要 Chart 管理，K8s Python 客户端直接 apply manifest 更简单 |
| **Terraform / Pulumi** | IaC 工具，本项目部署目标是用户现有集群，不管理基础设施 |
| **docker-py** | 不支持 Compose 和 Buildx，这两个是核心需求 |
| **Dulwich** | 纯 Python git 实现，容器里已有 git，无需牺牲性能 |
| **claude-code-sdk** | 已废弃，被 claude-agent-sdk 替代 |
| **Codex Python SDK** | 实验性，需要本地仓库 checkout，不适合容器化 |

---

## 10. 版本固定策略

- **精确固定** (`==`)：所有 Python 生产依赖，避免隐式升级破坏
- **主版本范围** (`^`)：前端 npm 依赖（package-lock.json 锁定实际版本）
- **定期审计**：每月 `pip-audit` + `npm audit`，关注安全补丁

---

*Research completed: 2026-04-23*
*Sources: PyPI, npm, GitHub releases, Anthropic docs, OpenAI docs, Kubernetes docs*
