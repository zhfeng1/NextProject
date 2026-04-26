# Project: NextProject

## What This Is

NextProject 是一个 AI 驱动的网站开发平台，用来把需求快速转化为可运行、可测试、可部署的网站，并统一管理多个站点的开发、测试与部署流程。它面向程序员，也希望让项目经理和普通用户能够以更低门槛参与网站构建与迭代。

## Core Value

快速、可迭代、质量可控地把需求变成可运行的网站；速度重要，但不能以测试能力、可维护性和可部署性为代价。

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- [x] 支持用户注册、登录与基础权限控制，作为站点管理和任务操作的入口
- [x] 支持多站点创建、列表、启动、停止、编辑、文件浏览和预览访问
- [x] 支持通过 Codex、Claude、Gemini 发起开发任务，并查看日志、历史和取消任务
- [x] 支持本地测试、任务编排以及 local / Apollo 两类部署配置与执行路径

### Active

<!-- Current scope being built toward. These are hypotheses until shipped. -->

- [ ] 把“需求 → 生成/调整 → 测试 → 部署”的主链路进一步打磨成快速且高质量的可迭代工作流
- [ ] 明显提升易用性，让程序员、项目经理和普通用户都能顺畅完成核心操作
- [ ] 强化平台可靠性与隔离能力，包括容器化子站点、版本回滚、监控告警和更稳定的任务执行能力

### Out of Scope

<!-- Explicit boundaries. Include reasoning to prevent re-adding. -->

- 只追求生成速度而牺牲质量保障 —— 这会直接违背产品定位中“快速并且可迭代、质量高”的核心要求
- 一开始就支持所有技术栈、所有部署平台与通用低代码能力 —— 当前应优先把既有 FastAPI + Vue + Docker / Apollo 主链路做深做稳

## Context

当前仓库是一个 brownfield 项目，已经具备可运行的前后端代码与 Docker 化基础设施：后端使用 FastAPI、SQLAlchemy、Celery、PostgreSQL、Redis、MinIO，前端使用 Vue 3、Vite、Pinia 和一组基于 Radix/shadcn 风格的 UI 组件。项目同时承载现有能力与演进中的目标能力，已有较完整的站点管理、任务执行、预览、部署与后台配置路径，但在容器隔离、模板资产、版本对比、测试覆盖、监控和一致性收敛方面仍有明显提升空间。

## Constraints

- **Product**: 易用性必须覆盖程序员、项目经理和普通用户 —— 目标用户不只是工程团队
- **Quality**: 迭代速度不能建立在牺牲测试、回滚能力和可维护性的基础上 —— 用户已明确拒绝“只求快”
- **Architecture**: 以 brownfield 方式渐进演进现有 FastAPI + Vue + Docker/Celery 架构 —— 降低重写风险并保留现有能力

## Tech Stack

- **Language**: Python + TypeScript
- **Framework**: FastAPI + Vue 3（Vite / Pinia）
- **Database**: PostgreSQL（并配合 Redis、MinIO 作为缓存与对象存储）

## Key Decisions

<!-- Decisions that constrain future work. Add throughout project lifecycle. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 采用 brownfield 渐进演进，而不是整体重写 | 当前仓库已有运行中的站点、任务、部署与配置能力，保留增量价值更稳妥 | Accepted |
| 优先追求“质量受控的快速迭代”，而不是单纯追求生成速度 | 产品定位和用户要求都强调质量不能被速度吞掉 | Accepted |
| 产品体验必须面向程序员、项目经理和普通用户三类人群优化 | 可用性决定该平台是否真正扩大使用边界 | Accepted |

## Stakeholders

- 程序员 / 开发者
- 项目经理 / 需求提出者
- 普通用户 / 非技术使用者
- 运维与部署维护者

---
*Last updated: 2026-04-20 after initialization*
