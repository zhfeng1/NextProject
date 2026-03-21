# Requirements: NextProject

**Defined:** 2026-04-23
**Core Value:** 用户描述需求后，AI 自动完成编码→测试→部署的完整流程

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### 项目管理 (PROJ)

- [ ] **PROJ-01**: 用户可创建项目并为项目命名和描述
- [ ] **PROJ-02**: 用户可在项目下关联多个 git 仓库（前端、后端、微服务等）
- [ ] **PROJ-03**: 用户可从零创建空白站点，平台自动初始化 git 仓库
- [ ] **PROJ-04**: 用户可通过 git URL 导入已有仓库代码
- [ ] **PROJ-05**: 用户可浏览项目下所有仓库的文件结构
- [ ] **PROJ-06**: AI 能感知项目下多个仓库的结构和服务边界，跨仓库理解上下文

### 用户认证 (AUTH)

- [ ] **AUTH-01**: 用户可通过邮箱和密码注册账号
- [ ] **AUTH-02**: 用户可登录并通过 JWT 保持会话
- [ ] **AUTH-03**: 用户可查看和编辑个人信息
- [ ] **AUTH-04**: 用户可登出

### API Key 管理 (KEY)

- [ ] **KEY-01**: 用户可配置自己的 Claude API Key，平台加密存储（Fernet）
- [ ] **KEY-02**: 用户可配置自己的 OpenAI API Key，平台加密存储
- [ ] **KEY-03**: 用户配置 API Key 后可验证连通性
- [ ] **KEY-04**: API Key 在 API 返回时脱敏处理（仅显示末 4 位）

### AI 编码 (CODE)

- [ ] **CODE-01**: 用户可输入自然语言需求描述，AI 自动拆解为子任务列表
- [ ] **CODE-02**: AI 按子任务依赖顺序逐步执行编码，修改对应仓库代码
- [ ] **CODE-03**: 用户可在编辑器内与 AI 对话，AI 逐步修改当前文件/仓库代码
- [ ] **CODE-04**: 编码任务支持状态跟踪（待处理/进行中/已完成/失败）
- [ ] **CODE-05**: 编码过程通过 WebSocket 实时推送日志到前端
- [ ] **CODE-06**: 用户可查看 AI 编码的 diff 变更
- [ ] **CODE-07**: AI 编码使用用户配置的 API Key 调用 Claude Code CLI 或 Codex CLI

### 测试 (TEST)

- [ ] **TEST-01**: AI 可根据代码变更生成 Playwright 测试用例草稿
- [ ] **TEST-02**: 用户可在前端查看、编辑测试用例
- [ ] **TEST-03**: 用户确认后可执行 Playwright 浏览器自动化测试
- [ ] **TEST-04**: 测试结果展示通过/失败状态、错误信息和截图
- [ ] **TEST-05**: 测试执行进度通过 WebSocket 实时推送

### 部署 (DEPL)

- [ ] **DEPL-01**: 编码完成后可自动触发 Docker 构建并本地部署预览
- [ ] **DEPL-02**: 用户可配置部署相关的环境变量，平台加密存储
- [ ] **DEPL-03**: 用户可通过预览 URL 访问本地部署的站点
- [ ] **DEPL-04**: 部署过程通过 WebSocket 推送构建和启动日志

### 安全加固 (SEC)

- [ ] **SEC-01**: 所有用户凭据（API Key、部署密码）加密存储，不明文落库
- [ ] **SEC-02**: AI 任务执行时通过临时文件传入 API Key，任务结束后删除
- [ ] **SEC-03**: 每个仓库的 AI 任务通过 Redis 分布式锁防止并发冲突

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### 部署扩展

- **DEPL-V2-01**: Skill 部署系统 — YAML 定义部署流程步骤，支持对接任意平台
- **DEPL-V2-02**: 微服务多应用批量部署
- **DEPL-V2-03**: 内置 K8s/Apollo 部署 Skill
- **DEPL-V2-04**: 部署回滚能力

### AI 增强

- **CODE-V2-01**: 错误自愈循环（AI 检测编码错误自动修复）
- **CODE-V2-02**: Token 消耗统计展示
- **CODE-V2-03**: 编码完成后自动触发测试生成

### 平台运营

- **OPS-V2-01**: 计费系统
- **OPS-V2-02**: 多租户隔离
- **OPS-V2-03**: 团队协作与权限管理

## Out of Scope

| Feature | Reason |
|---------|--------|
| 移动端适配 | Web 优先，后续考虑 |
| 实时协作编辑 | v1 单人编辑 |
| CI/CD 管道集成 | v1 专注平台内置流程 |
| 代码审查/PR 流程 | v1 不涉及 |
| 完全自治 Agent（Devin 模式） | 任务完成率低，用户失去控制感 |
| 浏览器内 IDE（WebContainers） | 技术门槛极高；已有 Monaco + 服务端执行 |
| 自建 Hosting/CDN | 不做云基础设施 |
| GitHub/GitLab 深度集成 | v1 用平台自管 git |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| KEY-01 | Phase 1 — 安全加固与基础设施加固 | Planned |
| KEY-02 | Phase 1 — 安全加固与基础设施加固 | Planned |
| KEY-03 | Phase 1 — 安全加固与基础设施加固 | Planned |
| KEY-04 | Phase 1 — 安全加固与基础设施加固 | Planned |
| SEC-01 | Phase 1 — 安全加固与基础设施加固 | Planned |
| SEC-02 | Phase 1 — 安全加固与基础设施加固 | Planned |
| SEC-03 | Phase 1 — 安全加固与基础设施加固 | Planned |
| PROJ-01 | Phase 2 — 多仓库项目模型 | Planned |
| PROJ-02 | Phase 2 — 多仓库项目模型 | Planned |
| PROJ-03 | Phase 2 — 多仓库项目模型 | Planned |
| PROJ-04 | Phase 2 — 多仓库项目模型 | Planned |
| PROJ-05 | Phase 2 — 多仓库项目模型 | Planned |
| CODE-01 | Phase 3 — AI 编码引擎 | Planned |
| CODE-02 | Phase 3 — AI 编码引擎 | Planned |
| CODE-03 | Phase 3 — AI 编码引擎 | Planned |
| CODE-04 | Phase 3 — AI 编码引擎 | Planned |
| CODE-05 | Phase 3 — AI 编码引擎 | Planned |
| CODE-06 | Phase 3 — AI 编码引擎 | Planned |
| CODE-07 | Phase 3 — AI 编码引擎 | Planned |
| PROJ-06 | Phase 3 — AI 编码引擎 | Planned |
| TEST-01 | Phase 4 — 半自动测试系统 | Planned |
| TEST-02 | Phase 4 — 半自动测试系统 | Planned |
| TEST-03 | Phase 4 — 半自动测试系统 | Planned |
| TEST-04 | Phase 4 — 半自动测试系统 | Planned |
| TEST-05 | Phase 4 — 半自动测试系统 | Planned |
| DEPL-01 | Phase 5 — Docker 部署与预览 | Planned |
| DEPL-02 | Phase 5 — Docker 部署与预览 | Planned |
| DEPL-03 | Phase 5 — Docker 部署与预览 | Planned |
| DEPL-04 | Phase 5 — Docker 部署与预览 | Planned |
| AUTH-01 | Phase 6 — 用户认证完善与生产加固 | Planned |
| AUTH-02 | Phase 6 — 用户认证完善与生产加固 | Planned |
| AUTH-03 | Phase 6 — 用户认证完善与生产加固 | Planned |
| AUTH-04 | Phase 6 — 用户认证完善与生产加固 | Planned |

**Coverage:**
- v1 requirements: 33 total (PROJ×6, AUTH×4, KEY×4, CODE×7, TEST×5, DEPL×4, SEC×3)
- Mapped to phases: 33
- Unmapped: 0

---
*Requirements defined: 2026-04-23*
*Last updated: 2026-04-23 after roadmap creation*
