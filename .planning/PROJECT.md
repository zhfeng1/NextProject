# NextProject

## What This Is

NextProject 是一个 SaaS AI 开发平台，让用户通过自然语言驱动 AI 完成编码、测试、部署的完整开发生命周期。用户配置自己的 Claude/OpenAI API Key，在平台上创建或导入项目（支持多仓库微服务架构），AI 自动拆解需求并编码实现，半自动生成和执行 Playwright 测试用例，通过 Docker 本地部署预览，最终通过可扩展的 Skill 机制发布到 K8s、Docker 或自定义平台。

## Core Value

用户描述需求后，AI 自动完成编码→测试→部署的完整流程，无需手动操作每个环节。

## Requirements

### Validated

已有系统中已实现的能力：

- ✓ FastAPI 后端框架与 API 路由结构 — existing
- ✓ Vue 3 + Vite 前端框架与组件库 — existing
- ✓ JWT 认证与用户管理基础 — existing
- ✓ Celery + Redis 异步任务队列 — existing
- ✓ WebSocket 实时日志推送 — existing
- ✓ Monaco 代码编辑器集成 — existing
- ✓ Docker Compose 多服务编排 — existing
- ✓ Codex MCP 桥接服务 — existing
- ✓ Playwright 测试基础设施 — existing
- ✓ 站点创建与 git 仓库管理基础 — existing
- ✓ Prometheus + Grafana 监控 — existing
- ✓ MinIO 对象存储 — existing

### Active

- [ ] 用户可配置自己的 Claude/OpenAI API Key 并验证连通性
- [ ] 用户可通过自然语言描述需求，AI 自动拆解为子任务并逐步编码实现
- [ ] 用户可在编辑器内与 AI 对话，AI 逐步修改代码（对话式编码）
- [ ] 开发任务支持状态跟踪（待处理/进行中/已完成/失败）
- [ ] 用户可创建项目并关联多个 git 仓库（微服务/前后端分离）
- [ ] 用户可从零创建站点，也可从任意 git 仓库导入代码
- [ ] AI 编码完成后自动生成 Playwright 测试用例草稿
- [ ] 用户可查看、修改测试用例后执行浏览器自动化测试
- [ ] 编码完成后自动 Docker 构建并本地部署预览
- [ ] 通过 Skill 机制定义部署流程（步骤化：获取 token→获取命名空间→推镜像→API 部署）
- [ ] 用户可配置部署环境变量（账号密码、命名空间、应用名称等）
- [ ] 支持微服务多应用批量部署
- [ ] 用户注册、登录、个人信息管理
- [ ] 系统代码健壮性达到生产可用水平

### Out of Scope

- 计费系统 — v1 不需要，后续里程碑考虑
- 多租户隔离 — v1 不需要，后续里程碑考虑
- 移动端适配 — Web 优先
- 实时协作编辑 — v1 单人编辑即可
- CI/CD 管道集成（GitHub Actions 等）— v1 专注平台内置流程
- 代码审查/PR 流程 — v1 不涉及

## Context

### 现有系统状态

项目已有较完整的基础架构：
- 前端：Vue 3 + Vite，Monaco 编辑器，Pinia 状态管理，Axios API 客户端
- 后端：FastAPI，SQLAlchemy ORM，Alembic 迁移，JWT 认证
- 异步：Celery worker + beat，Redis broker，WebSocket 日志推送
- 基建：Docker Compose 编排，Nginx 反代，Prometheus/Grafana 监控
- AI 集成：Codex MCP 桥接服务，UserLLMProvider 模型（API Key 管理基础）
- 站点管理：generated_sites/ 生成站点，git 仓库初始化，预览代理

### 技术生态

- AI 编码引擎：Claude Code CLI、OpenAI Codex CLI
- 浏览器测试：Playwright（已安装 Chromium）
- 容器化：Docker + Docker Compose（本地部署）
- 发布目标：Kubernetes API、Docker Registry、自定义平台 API（如 Apollo）

### 项目结构

- 前端：`frontend/`（Vue 3 + Vite）
- 后端：`backend/`（FastAPI）
- 主服务镜像：`main_service/`
- MCP 桥接：`codex_mcp/`
- 生成站点：`generated_sites/`
- 监控：`monitoring/`

## Constraints

- **Tech Stack**: 前端 Vue 3 + TypeScript，后端 Python FastAPI — 沿用现有技术栈
- **AI Provider**: 用户自带 API Key，平台不承担 AI 调用成本
- **Runtime**: Docker 环境必须，所有服务容器化运行
- **Browser Testing**: Playwright + Chromium，运行在服务端容器内
- **Deploy Skill**: 必须可扩展 — 新平台只需添加 Skill 文件，不改核心代码

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 用户自带 API Key | 平台不承担 AI 成本，用户掌控自己的额度 | — Pending |
| Skill 机制实现部署扩展 | 新平台只需添加 Skill 定义文件，不需修改核心代码 | — Pending |
| 项目级多仓库模型 | 支持微服务和前后端分离，一个项目可关联多个 git 仓库 | — Pending |
| 半自动测试流程 | AI 生成测试用例草稿，用户确认后执行，平衡自动化与可控性 | — Pending |
| v1 不含计费和多租户 | 先走通核心流程，降低复杂度 | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-23 after initialization*
