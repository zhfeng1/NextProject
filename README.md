# NextProject

## 启动

```bash
cp .env.example .env
docker compose up -d --build
```

> 说明：`main-service` 会挂载 `/var/run/docker.sock`，用于执行本地镜像构建与推送（Apollo 部署任务）。

## `.env` 配置

- `LLM_DIALOG_LOG_ENABLED`：是否打印与大模型的请求/响应对话日志（默认 `false`）
- `LLM_DIALOG_LOG_MAX_CHARS`：每个日志字段最大长度，超出自动截断（默认 `4000`）
- `SUB_SITE_PORT_START`：子网站内部进程端口起始值（默认 `19100`）
- `SUB_SITE_PORT_END`：子网站内部进程端口结束值（默认 `19999`）
- `AGENT_TASK_WORKERS`：任务 worker 数量（默认 `2`）
- `PLAYWRIGHT_BASE_URL`：Playwright 冒烟测试入口（默认 `http://127.0.0.1:8080`，容器内地址）
- `CODEX_CMD` / `CLAUDE_CMD` / `GEMINI_CMD`：三种 CLI 的默认执行命令
- `CODEX_AUTH_CMD` / `CLAUDE_AUTH_CMD` / `GEMINI_AUTH_CMD`：三种 CLI 的认证命令

## 端口

- 主服务（配置页 + 首页）：`http://localhost:18080`
- 子网站统一入口（通过主服务端口访问）：`http://localhost:18080/sites/{site_id}`

## 功能对应

- 容器启动时自动拉取主流 `AGENTS.md` 到 `./data/agents`（已存在则跳过不覆盖）。
- 首次打开是配置页，可配置：
  - OpenAI 兼容 API（`responses` / `chat_completions`）
  - Codex OAuth / MCP 相关配置
  - 交互式 Codex OAuth 引导（在页面内启动 `codex login --device-auth` 并查看状态）
- 顶部导航有两个按钮：`站点管理`、`后台配置`。
- 站点管理页（`/home`）支持：
  - 子网站增删查
  - 启动 / 停止
  - 进入站点编辑页
- 站点编辑页（`/site-editor/{site_id}`）支持：
  - 任务面板：开发任务（Codex/Claude/Gemini CLI）、Playwright 本地冒烟、部署任务（local/apollo）
  - 任务历史、任务日志查看、任务取消
  - Provider 命令配置、Apollo 部署配置维护
  - 普通调整、MCP 测试、实时预览

## 任务 API（核心）

- `POST /api/tasks`：创建任务（`develop_code` / `test_local_playwright` / `deploy_local` / `deploy_apollo`）
- `GET /api/tasks/{task_id}`：查看任务详情
- `GET /api/tasks/{task_id}/logs`：增量读取日志（`after_id`）
- `POST /api/tasks/{task_id}/cancel`：取消任务
- `GET /api/sites/{site_id}/tasks`：站点任务历史
- `POST /api/providers/{provider}/auth/start`：启动 Provider 认证引导
- `GET /api/providers/{provider}/auth/status`：查看认证状态
- `POST /api/providers/{provider}/auth/cancel`：取消认证引导

## Codex MCP 说明

- `docker compose` 会同步启动 `codex-mcp` 服务，镜像内已安装 Codex CLI。
- `codex-mcp` 容器启动时会自动拉起 `codex mcp-server`。
- OAuth 凭据持久化在：`./data/codex_home`。

## 项目亮点
- 适合企业级部署，与本地环境隔离。杜绝出现Codex删除本地文件的情况。
- 
