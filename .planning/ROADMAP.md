# Roadmap: NextProject v1

**Created:** 2026-04-23
**Granularity:** standard (6 phases, 3-5 plans each)
**Core Value:** 用户描述需求后，AI 自动完成编码→测试→部署的完整流程

---

## Phase 1: 安全加固与基础设施加固

**Goal:** 所有凭据加密存储，消除已知安全漏洞，为后续功能提供安全基础。

**Requirements:** SEC-01, SEC-02, SEC-03, KEY-01, KEY-02, KEY-03, KEY-04

**Plans:**
1. API Key 加密存储改造 — Fernet 加密 `UserLLMProvider.api_key`，迁移现有明文数据，API 返回脱敏 (KEY-01, KEY-02, KEY-04, SEC-01)
2. API Key 连通性验证端点 — 调用 Claude/OpenAI API 验证 Key 有效性 (KEY-03)
3. AI 任务安全执行机制 — 临时文件传入 API Key + 任务结束清理 + Redis 分布式锁 (SEC-02, SEC-03)

**Success Criteria:**
- 用户配置 API Key 后，数据库中存储的是密文，SQL 查询不可见明文
- API 返回 Key 信息时仅显示 `****last4`
- 用户点击"验证"按钮后 3 秒内得到连通性结果（成功/失败+错误信息）
- 同一仓库不可同时执行两个 AI 任务（第二个任务排队等待）

---

## Phase 2: 多仓库项目模型

**Goal:** 用户可以创建项目并关联多个 git 仓库，支持微服务和前后端分离架构。

**Requirements:** PROJ-01, PROJ-02, PROJ-03, PROJ-04, PROJ-05

**Plans:**
1. Project + ProjectRepo 数据模型与迁移 — 新建表、Site 添加可空 project_id FK、Alembic 迁移 (PROJ-01, PROJ-02)
2. 仓库创建与导入 — 空白站点初始化 git + 从 URL 克隆已有仓库 (PROJ-03, PROJ-04)
3. 项目管理前端 — 项目列表、创建/编辑、仓库管理、文件浏览器 (PROJ-01, PROJ-02, PROJ-05)
4. 文件浏览与 Monaco 集成 — 项目下多仓库文件树切换、Monaco 打开编辑文件 (PROJ-05)

**Success Criteria:**
- 用户可以创建项目、添加多个仓库（空白创建或 git URL 导入）
- 用户可以在项目视图中切换仓库，浏览各仓库的文件树
- 现有 Site 功能不受影响（向后兼容）
- 数据库迁移可逆（down revision 可回退）

---

## Phase 3: AI 编码引擎

**Goal:** 用户通过自然语言描述需求，AI 自动拆解为子任务并逐步编码，支持对话式交互。

**Requirements:** CODE-01, CODE-02, CODE-03, CODE-04, CODE-05, CODE-06, CODE-07, PROJ-06

**Plans:**
1. 需求拆解服务 — RequirementDecomposer 调用 LLM 将自然语言拆解为子任务列表 (CODE-01, PROJ-06)
2. Agent 编排与执行 — AgentOrchestrator 按依赖顺序调度 Celery 任务，支持 Claude Code CLI / Codex CLI (CODE-02, CODE-04, CODE-07)
3. 实时日志与 Diff 展示 — WebSocket 推送编码日志 + Monaco Diff Editor 展示变更 (CODE-05, CODE-06)
4. 对话式编码 — 编辑器内与 AI 对话，AI 逐步修改当前文件 (CODE-03)
5. 任务状态管理前端 — 需求输入 → 子任务列表 → 状态跟踪面板 (CODE-01, CODE-04)

**Success Criteria:**
- 用户输入自然语言需求后看到 AI 拆解的子任务列表
- 子任务依次执行，每个任务状态实时更新（待处理→进行中→已完成/失败）
- 编码过程中用户可在终端面板实时看到日志输出
- 编码完成后用户可查看文件级 diff
- 用户可在编辑器中与 AI 对话，AI 修改代码并显示变更

---

## Phase 4: 半自动测试系统

**Goal:** AI 根据代码变更生成 Playwright 测试用例草稿，用户审核后执行，展示结果。

**Requirements:** TEST-01, TEST-02, TEST-03, TEST-04, TEST-05

**Plans:**
1. 测试数据模型与 CRUD — TestSuite, TestCase, TestRun 表 + API (TEST-02)
2. AI 测试生成 — TestGenerationService 根据 diff 调用 LLM 生成 Playwright 测试草稿 (TEST-01)
3. 测试执行引擎 — Celery task 运行 Playwright，WebSocket 推送进度 (TEST-03, TEST-05)
4. 测试结果展示 — 通过/失败状态、错误信息、截图上传 MinIO 并展示 (TEST-04)

**Success Criteria:**
- AI 编码完成后用户可一键触发测试用例生成
- 用户可在前端编辑生成的测试代码
- 用户点击"执行"后测试在服务端运行，进度实时推送
- 测试完成后展示每个用例的通过/失败状态、错误详情、失败截图

---

## Phase 5: Docker 部署与预览

**Goal:** 编码完成后自动构建 Docker 镜像并本地部署，用户可通过预览 URL 访问。

**Requirements:** DEPL-01, DEPL-02, DEPL-03, DEPL-04

**Plans:**
1. Docker 构建流水线 — python-on-whales 调用 Compose/Buildx 构建项目镜像 (DEPL-01)
2. 部署环境变量管理 — 加密存储环境变量，构建时注入 (DEPL-02)
3. 本地部署与预览代理 — Compose up + Nginx 反代预览 URL (DEPL-03, DEPL-04)

**Success Criteria:**
- 编码完成后用户可一键触发 Docker 构建
- 构建和部署日志通过 WebSocket 实时推送
- 部署完成后用户获得预览 URL，点击即可访问运行中的应用
- 用户可配置部署环境变量，变量加密存储

---

## Phase 6: 用户认证完善与生产加固

**Goal:** 完善用户认证流程，整体系统达到生产可用水平。

**Requirements:** AUTH-01, AUTH-02, AUTH-03, AUTH-04

**Plans:**
1. 注册与登录流程完善 — 邮箱注册、密码强度校验、JWT 会话管理 (AUTH-01, AUTH-02)
2. 用户信息管理 — 个人信息查看/编辑、登出 (AUTH-03, AUTH-04)
3. 端到端集成测试与 Bug 修复 — 全流程冒烟测试，修复集成问题

**Success Criteria:**
- 新用户可通过邮箱注册、登录，JWT 正常维持会话
- 用户可编辑个人信息、正常登出
- 全流程（注册→配 Key→创建项目→AI 编码→测试→部署预览）可顺畅走通

---

## Phase Dependencies

```
Phase 1 (安全加固) ─────┐
                         ├──→ Phase 3 (AI 编码) ──→ Phase 4 (测试)
Phase 2 (项目模型) ─────┘                               │
                         │                               ▼
                         └─────────────────────→ Phase 5 (部署)
                                                         │
Phase 6 (认证加固) ◄─── 可在任何阶段并行 ────────────────┘
```

**说明：**
- Phase 1 和 Phase 2 可以并行，但都必须在 Phase 3 之前完成
- Phase 4（测试）依赖 Phase 3（AI 编码）的 LLM 调用能力
- Phase 5（部署）依赖 Phase 2（项目模型）
- Phase 6（认证）相对独立，因为已有 JWT 基础，可与其他阶段并行；放在最后确保集成测试覆盖全流程

---

## Coverage Verification

| Requirement | Phase | Status |
|-------------|-------|--------|
| SEC-01 | Phase 1 | Planned |
| SEC-02 | Phase 1 | Planned |
| SEC-03 | Phase 1 | Planned |
| KEY-01 | Phase 1 | Planned |
| KEY-02 | Phase 1 | Planned |
| KEY-03 | Phase 1 | Planned |
| KEY-04 | Phase 1 | Planned |
| PROJ-01 | Phase 2 | Planned |
| PROJ-02 | Phase 2 | Planned |
| PROJ-03 | Phase 2 | Planned |
| PROJ-04 | Phase 2 | Planned |
| PROJ-05 | Phase 2 | Planned |
| PROJ-06 | Phase 3 | Planned |
| CODE-01 | Phase 3 | Planned |
| CODE-02 | Phase 3 | Planned |
| CODE-03 | Phase 3 | Planned |
| CODE-04 | Phase 3 | Planned |
| CODE-05 | Phase 3 | Planned |
| CODE-06 | Phase 3 | Planned |
| CODE-07 | Phase 3 | Planned |
| TEST-01 | Phase 4 | Planned |
| TEST-02 | Phase 4 | Planned |
| TEST-03 | Phase 4 | Planned |
| TEST-04 | Phase 4 | Planned |
| TEST-05 | Phase 4 | Planned |
| DEPL-01 | Phase 5 | Planned |
| DEPL-02 | Phase 5 | Planned |
| DEPL-03 | Phase 5 | Planned |
| DEPL-04 | Phase 5 | Planned |
| AUTH-01 | Phase 6 | Planned |
| AUTH-02 | Phase 6 | Planned |
| AUTH-03 | Phase 6 | Planned |
| AUTH-04 | Phase 6 | Planned |

**Total: 33 requirements mapped (27 original + 6 KEY requirements counted separately from v1 list)**
**Unmapped: 0**

---
*Roadmap created: 2026-04-23*
*Last updated: 2026-04-23*
