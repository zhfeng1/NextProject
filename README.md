# NextProject

## 启动

```bash
cp .env.example .env
./start.sh --build
```

> 说明：`main-service` 会挂载 `/var/run/docker.sock`，用于执行本地镜像构建与推送（Apollo 部署任务）。

默认会启动数据库、缓存、对象存储、主服务、Celery、前端，以及 Codex、Claude Code、CodeBuddy、OpenCode 四个独立编程工具适配器。适配器仅连接 Docker 内部网络，不向宿主机暴露端口。

按需启用可选服务：

```bash
# 启动核心服务 + Flower/Prometheus/Grafana
./start.sh --monitoring

# 启动核心服务 + Celery Beat 定时调度器
./start.sh --scheduler

# 启动核心服务 + 所有可选运行服务
./start.sh --all

# 单独运行后端测试
docker compose run --rm test
```

## `.env` 配置

- `LLM_DIALOG_LOG_ENABLED`：是否打印与大模型的请求/响应对话日志（默认 `false`）
- `LLM_DIALOG_LOG_MAX_CHARS`：每个日志字段最大长度，超出自动截断（默认 `4000`）
- `SUB_SITE_PORT_START`：子网站内部进程端口起始值（默认 `19100`）
- `SUB_SITE_PORT_END`：子网站内部进程端口结束值（默认 `19999`）
- `AGENT_TASK_WORKERS`：任务 worker 数量（默认 `2`）
- `PLAYWRIGHT_BASE_URL`：Playwright 冒烟测试入口（默认 `http://127.0.0.1:8080`，容器内地址）
- `PROGRAMMING_TOOL_ADAPTER_TOKEN`：主服务、Celery 与编程工具适配器之间的内部鉴权令牌
- `CODEX_ADAPTER_URL` / `CLAUDE_CODE_ADAPTER_URL` / `CODEBUDDY_ADAPTER_URL` / `OPENCODE_ADAPTER_URL` / `KIMI_CODE_ADAPTER_URL`：适配器内网地址

## 端口

- 主服务（配置页 + 首页）：`http://localhost:18080`
- 子网站统一入口（通过主服务端口访问）：`http://localhost:18080/sites/{site_id}`

## 功能对应

- 容器启动时自动拉取主流 `AGENTS.md` 到 `./data/agents`（已存在则跳过不覆盖）。
- 项目页面可配置三类模型接口：OpenAI Responses、Claude Messages 和 OpenAI Chat Completions。同一项目每种接口只能启用一个 Provider。
- 编程任务优先使用项目级 Provider；当前项目没有兼容配置时回退全局 Provider，但不会回退编程工具 CLI 的共享登录态。每个作用域内按 `Responses > Messages > Chat Completions` 选择兼容配置。
- 顶部导航有两个按钮：`站点管理`、`后台配置`。
- 站点管理页（`/home`）支持：
  - 子网站增删查
  - 启动 / 停止
  - 进入站点编辑页
- 项目管理页新建项目时会默认创建一个 `app` 仓库，仓库源码来自内置 `python-vue-starter`，可直接进入编辑、任务和预览流程。
- 空白站点/空白仓库默认使用 Python/FastAPI + 静态前端 starter；预览启动命令为 `python -m uvicorn backend.app:app --host 0.0.0.0 --port $PORT`，可使用仓库内 Dockerfile/docker-compose 离线部署，不依赖 Cloudflare Worker、Sites 托管或 OpenAI 托管元数据。
- 站点编辑页（需先登录，访问路径：`/sites/{site_id}/edit`）支持：
  - 任务面板：开发任务（Codex、CodeBuddy、OpenCode）、Playwright 本地冒烟、部署任务（local/apollo）
  - 任务历史、任务日志查看、任务取消
  - 编程工具命令配置、Apollo 部署配置维护
  - 普通调整、MCP 测试、实时预览

## 任务 API（核心）

- `POST /api/tasks`：创建任务（`develop_code` / `test_local_playwright` / `deploy_local` / `deploy_apollo`）
- `GET /api/tasks/{task_id}`：查看任务详情
- `GET /api/tasks/{task_id}/logs`：增量读取日志（`after_id`）
- `POST /api/tasks/{task_id}/cancel`：取消任务
- `GET /api/sites/{site_id}/tasks`：站点任务历史
- `POST /api/providers/{provider}/auth/start`：启动编程工具认证引导
- `GET /api/providers/{provider}/auth/status`：查看认证状态
- `POST /api/providers/{provider}/auth/cancel`：取消认证引导

## 编程工具适配器

- `docker compose` 会分别启动 `codex-adapter`、`claude-code-adapter`、`codebuddy-adapter`、`opencode-adapter`、`kimi-code-adapter`。
- 主服务和 Celery 通过 NDJSON 流调用适配器，不再直接安装或执行编程工具 CLI。
- 面向用户的 AI 输出仅包含适配器的 `display_delta`；命令、代码片段和原始结构化事件只保存在非公开调试产物中。
- OAuth 凭据持久化在：`./data/codex_home`。

## 项目亮点
- 适合企业级部署，与本地环境隔离。杜绝出现Codex删除本地文件的情况。
- 
