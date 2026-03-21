# Phase 1: 安全加固与基础设施加固 - Context

**Gathered:** 2026-04-23
**Status:** Ready for planning

<domain>
## Phase Boundary

所有凭据加密存储，消除已知安全漏洞，为后续功能提供安全基础。覆盖需求：SEC-01, SEC-02, SEC-03, KEY-01, KEY-02, KEY-03, KEY-04。

</domain>

<decisions>
## Implementation Decisions

### 加密方案与迁移
- **D-01:** Fernet 加密密钥通过环境变量管理（.env + pydantic-settings），与项目现有配置模式一致
- **D-02:** 现有明文 API Key 通过 Alembic 数据迁移自动加密——迁移脚本读取明文、加密后回写，用户无感
- **D-03:** 加解密在应用层实现——写入数据库前加密，读取后解密。api_key 字段保持 Text 类型不变

### API 返回脱敏
- **D-04:** API 返回中 API Key 脱敏格式为 `sk-****abcd`（保留前缀+末4位），便于用户识别
- **D-05:** 所有返回 provider 对象的端点（list/create/update）全部脱敏，永远不返回明文 Key

### 模型连通性验证
- **D-06:** 不需要单独的 API Key 验证端点。验证的是**模型可用性**，而非 Key 有效性
- **D-07:** 验证方式：向选定模型发送轻量级 "hi" 请求，确认模型可正常响应
- **D-08:** 需要适配三种 API 格式：OpenAI Completion (`/v1/chat/completions`)、OpenAI Response (`/v1/responses`)、Claude Message (`/v1/messages`)
- **D-09:** 验证由用户手动触发（点击"验证"按钮），不在保存时自动验证

### 任务安全执行
- **D-10:** AI 任务执行时通过临时文件传入 API Key，任务结束后删除。避免 Key 出现在进程参数列表中
- **D-11:** Redis 分布式锁按仓库（site_id/repo_id）粒度锁定，同一仓库同时只允许一个 AI 任务
- **D-12:** 获取锁失败时任务进入队列等待，前一个任务完成后自动开始

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 安全相关
- `backend/models/user_llm_provider.py` — UserLLMProvider 模型，api_key 字段当前为明文 Text
- `backend/api/v2/providers.py` — Provider CRUD 端点，_serialize() 需要加脱敏逻辑
- `backend/core/security.py` — 现有认证/安全模块，Fernet 加密工具可放在此处或新建模块
- `backend/core/config.py` — pydantic-settings 配置，需要添加 FERNET_KEY 配置项

### 数据库迁移
- `backend/alembic/versions/20260323_0004_add_user_llm_providers.py` — UserLLMProvider 原始迁移

### 任务执行
- `backend/services/task_service.py` — 任务服务，API Key 传递和锁机制的集成点
- `backend/core/celery_app.py` — Celery 配置，Redis 连接已配置
- `backend/tasks/develop_code.py` — AI 编码任务，需要改为临时文件读取 Key

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/core/config.py` (pydantic-settings): 已有 .env 加载模式，可直接添加 FERNET_KEY
- `backend/core/security.py`: 已有 JWT 和密码哈希逻辑，可扩展加密/解密工具函数
- `backend/api/v2/providers.py` 的 `fetch-models` 端点: 已有 httpx 调用外部 API 的模式
- Redis 已在架构中 (Celery broker): 可直接用于分布式锁

### Established Patterns
- Service singleton 模式: `site_service`, `task_service` 等
- HTTPException 统一错误处理
- `{"ok": True/False, ...}` JSON 响应格式
- Alembic 数据迁移 + data migration

### Integration Points
- `_serialize()` in `providers.py:17` — 脱敏逻辑的插入点
- `task_service.py` 中任务创建流程 — 临时文件和锁的插入点
- `docker-compose.yml` — 需要添加 FERNET_KEY 环境变量

</code_context>

<specifics>
## Specific Ideas

- 模型验证需支持三种 API 格式（OpenAI Completion/Response + Claude Message），根据 provider 的 format 字段选择对应的 API 调用方式
- 队列等待机制：任务提交时获取锁失败不拒绝，而是排队等待自动执行

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-security-hardening*
*Context gathered: 2026-04-23*
