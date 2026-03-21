# Phase 1: 安全加固与基础设施加固 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-23
**Phase:** 01-安全加固与基础设施加固
**Areas discussed:** 加密方案与迁移, API 返回脱敏, Key 连通性验证, 任务安全执行

---

## 加密方案与迁移

### Fernet 加密密钥存储位置

| Option | Description | Selected |
|--------|-------------|----------|
| 环境变量（推荐） | Fernet 密钥放在 .env 中，通过 settings 加载。项目已有 .env + pydantic-settings 模式 | ✓ |
| Docker Secrets | 以文件形式注入密钥，更安全但需要额外配置 Docker Compose | |
| Claude 决定 | 交由 Claude 决定 | |

**User's choice:** 环境变量（推荐）

### 现有明文数据迁移策略

| Option | Description | Selected |
|--------|-------------|----------|
| 迁移时自动加密（推荐） | Alembic 迁移时自动读取明文加密回写，一次性完成 | ✓ |
| 双模式兼容 | 应用层读取时试解密，失败视为明文并重新加密存储 | |
| Claude 决定 | 交由 Claude 决定 | |

**User's choice:** 迁移时自动加密（推荐）

### 加密实现层

| Option | Description | Selected |
|--------|-------------|----------|
| 应用层加解密（推荐） | 字段保持 Text 类型，写入前加密，读取后解密 | ✓ |
| SQLAlchemy TypeDecorator | 自定义类型在 ORM 层透明加解密 | |

**User's choice:** 应用层加解密（推荐）

---

## API 返回脱敏

### 脱敏格式

| Option | Description | Selected |
|--------|-------------|----------|
| 前缀+末4位（推荐） | 显示为 sk-****abcd 格式，保留前缀和末4位 | ✓ |
| 仅末4位 | 显示为 ****abcd 格式 | |
| Claude 决定 | 交由 Claude 决定 | |

**User's choice:** 前缀+末4位（推荐）

### 脱敏范围

| Option | Description | Selected |
|--------|-------------|----------|
| 全部脱敏（推荐） | 所有返回 provider 对象的端点都脱敏，永远不返回明文 | ✓ |
| 部分脱敏 | 列表接口脱敏，详情/编辑接口返回明文 | |

**User's choice:** 全部脱敏（推荐）

---

## Key 连通性验证

### 验证方式

| Option | Description | Selected |
|--------|-------------|----------|
| 获取模型列表（推荐） | 调用 /models 端点获取模型列表，复用 fetch-models 逻辑 | |
| 轻量级 Completion | 发送最小化 completion 请求验证端到端可用性 | |
| Claude 决定 | 交由 Claude 决定 | |

**User's choice:** Other — Key 有效性不需要验证，模型有效性使用 hi 请求验证，要支持 OpenAI 的 completion、Response 和 Claude 的 message 接口
**Notes:** 用户重新定义了需求范围：不验证 Key，只验证模型可用性。需要适配三种 API 格式。

### 验证触发时机

| Option | Description | Selected |
|--------|-------------|----------|
| 手动触发验证（推荐） | 用户选择模型后点击"验证"按钮触发 | ✓ |
| 保存时自动验证 | 每次保存 provider 配置时自动验证所有模型 | |

**User's choice:** 手动触发验证（推荐）

---

## 任务安全执行

### API Key 传递方式

| Option | Description | Selected |
|--------|-------------|----------|
| 临时文件（推荐） | 任务启动时写入临时文件，CLI 通过文件路径读取，任务结束后删除 | ✓ |
| 环境变量 | 通过环境变量传入 Celery worker 进程 | |
| Claude 决定 | 交由 Claude 决定 | |

**User's choice:** 临时文件（推荐）

### 分布式锁粒度

| Option | Description | Selected |
|--------|-------------|----------|
| 按仓库锁定（推荐） | 以 site_id/repo_id 为锁键，同一仓库同时只允许一个 AI 任务 | ✓ |
| 按用户锁定 | 以 user_id 为锁键，同一用户同时只能执行一个 AI 任务 | |

**User's choice:** 按仓库锁定（推荐）

### 锁冲突处理

| Option | Description | Selected |
|--------|-------------|----------|
| 拒绝并提示（推荐） | 返回 409，前端提示"该仓库正在执行 AI 任务" | |
| 队列等待 | 任务进入等待队列，前一个完成后自动开始 | ✓ |
| Claude 决定 | 交由 Claude 决定 | |

**User's choice:** 队列等待

---

## Claude's Discretion

无 — 所有决策均由用户明确指定。

## Deferred Ideas

无 — 讨论保持在 Phase 1 范围内。
