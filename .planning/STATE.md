---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 02
current_plan: 4
status: executing
last_updated: "2026-04-23T07:33:00.000Z"
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 7
  completed_plans: 3
  percent: 42
---

# Project State: NextProject v1

**Current Phase:** 02
**Current Plan:** 4
**Status:** Executing Phase 02

---

## Phase Progress

| Phase | Name | Status | Plans | Completed |
|-------|------|--------|-------|-----------|
| 1 | 安全加固与基础设施加固 | NOT_STARTED | 3 | 0 |
| 2 | 多仓库项目模型 | IN_PROGRESS | 4 | 3 |
| 3 | AI 编码引擎 | NOT_STARTED | 5 | 0 |
| 4 | 半自动测试系统 | NOT_STARTED | 4 | 0 |
| 5 | Docker 部署与预览 | NOT_STARTED | 3 | 0 |
| 6 | 用户认证完善与生产加固 | NOT_STARTED | 3 | 0 |

## Current Context

- 项目已有完整基础架构（FastAPI + Vue3 + Celery + WebSocket + Docker Compose）
- JWT 认证基础已存在，但注册/登录/用户管理需完善
- API Key 存储存在明文安全风险，需优先修复
- Site 管理已有，需扩展为 Project 多仓库模型
- **Plan 02-01 已完成**: Project 数据模型 + Site.project_id FK + Alembic 迁移
- **Plan 02-02 已完成**: ProjectService CRUD + REST API + clone_repo Celery 任务 + 文件浏览 override_root

- **Plan 02-03 已完成**: 前端项目管理页面（TypeScript 类型、API 客户端、Pinia store、ProjectList/ProjectDetail、路由、侧边栏）

## Blockers

None

## Recent Decisions

| Decision | Date | Context |
|----------|------|---------|
| 安全加固优先于功能开发 | 2026-04-23 | API Key 明文存储是平台级风险 |
| Phase 1/2 可并行，3 依赖 1+2 | 2026-04-23 | 研究建议的构建顺序 |
| v1 不含 Skill 部署，推迟到 v2 | 2026-04-23 | 聚焦 Docker 本地部署预览 |
| 使用 mixins.py 的 UUIDPrimaryKeyMixin | 2026-04-23 | Plan 02-01: 与 Site 模型 String(36) PK 保持一致 |
| project_id 设为 nullable | 2026-04-23 | Plan 02-01: 保持向后兼容 |
| 迁移用 copy-verify-delete 策略 | 2026-04-23 | Plan 02-01: 文件系统迁移安全策略 |
| 使用 encrypt_api_key 而非 encrypt_value | 2026-04-23 | Plan 02-02: 匹配现有加密 API |
| resolve_site_path 返回 (root, target) 元组 | 2026-04-23 | Plan 02-02: 支持 override_root 同时保持路径穿越检查 |

| ProjectEditor 路由延迟到 Plan 04 | 2026-04-23 | Plan 02-03: 避免引用不存在的组件导致构建失败 |

---
*Last updated: 2026-04-23*

**Completed Plan:** 02-03 (项目管理前端 — 列表、创建、路由、导航) — 2026-04-23
**Next Plan:** 02-04
