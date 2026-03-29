# Phase 2: 多仓库项目模型 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-23
**Phase:** 02-多仓库项目模型
**Areas discussed:** Project 与 Site 关系, 仓库存储与导入, 前端项目视图, Monaco 文件编辑集成

---

## Project 与 Site 关系

| Option | Description | Selected |
|--------|-------------|----------|
| Site 作为 Project 的仓库 | Site 成为 Project 下的子级，每个 Site 对应一个仓库。Project 是新的顶层概念 | ✓ |
| Project 与 Site 完全独立 | 新建独立 ProjectRepo 表，Site 和 ProjectRepo 平级共存 | |
| Site 可选归属 Project | Site 表添加可空 project_id FK，既可独立存在也可归属项目 | |

**User's choice:** Site 作为 Project 的仓库
**Notes:** 无额外说明

| Option | Description | Selected |
|--------|-------------|----------|
| 自动迁移为单仓库项目 | 每个现有 Site 自动创建同名 Project，Site 归入其下。用户无感 | ✓ |
| 旧 Site 不迁移，新建必须走 Project | 现有 Site 保持独立，只有新建的才必须属于 Project | |

**User's choice:** 自动迁移为单仓库项目
**Notes:** 无额外说明

| Option | Description | Selected |
|--------|-------------|----------|
| 完全替换为"项目" | 彻底移除 Site 概念，前端只有"项目"入口 | ✓ |
| 并行存在 Sites + Projects | 保留 Sites 菜单项，新增 Projects 菜单项 | |

**User's choice:** 完全替换为"项目"
**Notes:** 无额外说明

| Option | Description | Selected |
|--------|-------------|----------|
| Site 表添加 project_id FK | 新建 Project 表，Site 表通过 FK 关联。仓库继承原 Site 的大部分字段 | ✓ |
| 新建 ProjectRepo 表替代 Site | 把仓库相关字段从 Site 抽离出来，Site 表用于其他用途 | |

**User's choice:** Site 表添加 project_id FK
**Notes:** 无额外说明

---

## 仓库存储与导入

| Option | Description | Selected |
|--------|-------------|----------|
| 按项目分组 | 目录结构变为 `generated_sites/<project_id>/<repo_name>/` | ✓ |
| 保持扁平结构 | 保持现有 `generated_sites/<site_id>/` 结构不变 | |

**User's choice:** 按项目分组
**Notes:** 无额外说明

| Option | Description | Selected |
|--------|-------------|----------|
| 仅 HTTPS 公开仓库 | 只支持公开仓库克隆，不处理认证 | |
| 支持私有仓库（token/SSH） | 支持 HTTPS + token 和 SSH 两种认证方式 | ✓ |

**User's choice:** 支持私有仓库（token/SSH）
**Notes:** 无额外说明

| Option | Description | Selected |
|--------|-------------|----------|
| 异步克隆 + 进度通知 | Celery 异步执行 git clone，WebSocket 推送进度 | ✓ |
| 同步克隆 | 同步执行 git clone，等待完成后返回 | |

**User's choice:** 异步克隆 + 进度通知
**Notes:** 无额外说明

---

## 前端项目视图

| Option | Description | Selected |
|--------|-------------|----------|
| 卡片网格布局 | 每个项目一张卡片，显示名称、仓库数、最后活动时间 | ✓ |
| 列表表格布局 | 紧凑表格形式 | |

**User's choice:** 卡片网格布局
**Notes:** 无额外说明

| Option | Description | Selected |
|--------|-------------|----------|
| 左右分栏 | 左侧仓库列表/文件树，右侧内容区 | |
| Tab 切换仓库 | 顶部 Tab 切换仓库，下方显示当前仓库内容 | ✓ |

**User's choice:** Tab 切换仓库
**Notes:** 无额外说明

| Option | Description | Selected |
|--------|-------------|----------|
| 完全重命名为 Projects | /sites → /projects，Views/Sites → Views/Projects | ✓ |
| 新建 Projects + 保留 Sites 作为子视图 | 新建 Projects 视图，Sites 视图保留作为仓库级别编辑入口 | |

**User's choice:** 完全重命名为 Projects
**Notes:** 无额外说明

---

## Monaco 文件编辑集成

| Option | Description | Selected |
|--------|-------------|----------|
| 单仓库文件树 | 一次只显示当前 Tab 选中仓库的文件，切换 Tab 切换文件树 | ✓ |
| 合并文件树 | 文件树顶层显示所有仓库名，展开后显示各仓库文件 | |

**User's choice:** 单仓库文件树
**Notes:** 无额外说明

| Option | Description | Selected |
|--------|-------------|----------|
| 多标签页 + 仓库前缀 | 标签页显示仓库前缀区分来源，切换仓库不关闭已打开的标签 | ✓ |
| 单文件模式 | 每次只能打开一个文件 | |

**User's choice:** 多标签页 + 仓库前缀
**Notes:** 无额外说明

---

## Claude's Discretion

无

## Deferred Ideas

无
