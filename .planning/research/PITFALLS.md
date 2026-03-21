# Pitfalls Research

**Analysis Date:** 2026-04-23
**Scope:** NextProject AI 开发平台扩展阶段常见陷阱

---

## 1. AI Coding Agent Orchestration

### 1.1 API Key 在进程环境中泄露

**现状：** `task_service.py:594-598` 将用户 API Key 直接写入子进程环境变量（`CODEX_TASK_API_KEY`、`ANTHROPIC_API_KEY`）。Celery worker 共享同一容器，任意并发任务可通过 `/proc/<pid>/environ` 读取其他任务的 Key。

**预警信号：** 多用户同时执行开发任务时，日志中出现非自己 Key 前缀的错误信息。

**防范策略：**
- 每个任务通过临时文件传递 Key，任务结束后删除（`mktemp` + `trap cleanup EXIT`）
- 或将 Key 通过 stdin pipe 传入子进程，不经过环境变量
- 长期方案：每用户独立 worker 容器或 seccomp 沙箱

**阶段：** Phase 1（API Key 管理功能）

### 1.2 无 Token/Cost 上限控制导致账单失控

**现状：** `run_shell_command` 的 `timeout_sec=1800` 是唯一限制。Claude Code 和 Codex 没有 token 上限参数，一次复杂 prompt 可能消耗数十美元。用户 API Key 被代用时没有任何费用预估或确认机制。

**预警信号：** 用户反馈 API 额度被迅速耗尽，单任务运行时间超过 10 分钟无进展。

**防范策略：**
- 在任务创建前对 prompt 长度做硬限制（如 32K 字符），拒绝过长输入
- Claude Code 支持 `--max-tokens` 参数，Codex 支持 `--max-tokens`，必须在构造命令时传入
- 增加任务级 cost estimation：调 API 前先用 tokenizer 估算输入 token 数，超过阈值时要求用户确认
- 为每用户设置日/月累计 token 用量上限（即使用户自带 Key，平台也应有安全阈值）

**阶段：** Phase 1（核心 AI 任务流程）

### 1.3 Provider Failover 静默切换用户未授权的 Key

**现状：** `run_develop_task` 第 447-476 行实现了 provider failover（codex -> claude_code -> gemini_cli）。切换 provider 后，会查询该用户对应 format 的 LLM provider 记录，但用户可能只配置了一个 provider 的 Key。Failover 到没有配置 Key 的 provider 时，会 fallback 到环境默认命令（第 630-636 行），此时使用的是平台全局 Key 而非用户 Key。

**预警信号：** 用户设置了 Codex provider，任务失败后自动切到 Claude Code，但日志显示 "Provider 配置: 环境默认"。

**防范策略：**
- Failover 前检查目标 provider 是否有对应的 `UserLLMProvider` 记录，没有则跳过
- 明确区分 "用户无此 provider 配置" 和 "provider 暂时不可用" 两种情况
- 如果所有 provider 都不可用，给出明确的错误消息而非静默尝试环境默认

**阶段：** Phase 1（AI 任务流程）

### 1.4 命令注入风险

**现状：** `task_service.py:574` 使用 `shlex.split(command_text)` 解析用户传入的 command 字段，直接作为子进程参数执行。虽然 `create_subprocess_exec` 不经过 shell，但 Codex 路径（第 600-613 行）使用了 `sh -lc` 包装，其中拼接了环境变量，存在间接注入风险。

**预警信号：** payload 中 command 字段包含 `; rm -rf` 等内容。

**防范策略：**
- 如果用户可以传入自定义 command，必须白名单校验可执行文件路径
- `sh -lc` 中的变量替换使用 `${}` 引用而非拼接（当前代码已正确使用 `"$@"` 传参，但应添加防护注释确保未来不退化）
- 对非管理员用户禁止自定义 command 字段

**阶段：** Phase 1

### 1.5 Celery `asyncio.run()` 在 Worker 中的事件循环冲突

**现状：** `develop_code.py`、`deploy.py`、`test.py` 每个 Celery task 都调用 `asyncio.run(_run())`。如果 Celery worker 使用 gevent/eventlet pool，或者未来切换到 async worker，`asyncio.run()` 会因为已有事件循环而崩溃。目前 `-c 4` 使用 prefork 模式暂时安全。

**预警信号：** 升级 Celery 或切换 pool 后出现 `RuntimeError: This event loop is already running`。

**防范策略：**
- 在 Celery task 中使用 `asyncio.run()` 是可行的，但需在文档/注释中明确标记 prefork-only 约束
- 考虑使用 `celery-pool-asyncio` 或在 task helper 中统一管理事件循环创建
- 部署配置中锁定 `--pool=prefork`

**阶段：** Phase 2（任务系统优化时）

---

## 2. Multi-Repo Project Management

### 2.1 现有 Site 模型不支持多仓库

**现状：** `Site` 模型是扁平结构（一个 site_id 对应一个 `generated_sites/<site_id>/` 目录）。git_url 存在 `site.config["git_source"]` 中，是单值。需求要求 "一个项目关联多个 git 仓库"，但没有 Project 实体。

**预警信号：** 尝试在 Site 上加 `repos: list[Repo]` 关系后，发现 task_service、site_service、deploy_service 全部耦合在 `site.site_id` + 单目录结构上。

**防范策略：**
- 引入 `Project` 实体作为顶层容器，`Site` 变成 Project 下的子仓库（或引入 `Repo` 作为 Site 的子实体）
- 关键设计决策：AI 任务的工作目录（cwd）应该是哪个仓库？需要在 payload 中明确 `repo_id`
- **先设计数据模型和 API 再写代码**，否则 Alembic 迁移会产生大量数据兼容问题
- 保持向后兼容：单仓库 Site 应该像 "只有一个 repo 的 project" 一样工作

**阶段：** Phase 2（多仓库功能）

### 2.2 并发 AI 任务修改同一仓库导致 Git 冲突

**现状：** 多个 Celery worker 可以同时拿到同一个 site 的 develop_code 任务（没有互斥锁）。两个 AI agent 同时修改 `generated_sites/xxx/` 下的文件，git 状态会混乱。

**预警信号：** 任务 A 成功但 diff 丢失，或 git status 出现 untracked/conflicted 文件导致后续任务失败。

**防范策略：**
- 为每个 site_id 实现 distributed lock（Redis `SETNX` 或 Celery chain 串行化）
- 或使用 git worktree：每个任务在独立 worktree 中执行，完成后 merge 回主分支
- 最低要求：在 `create_task` 中检查该 site 是否有 RUNNING 状态的 develop_code 任务，有则拒绝

**阶段：** Phase 2

### 2.3 文件系统隔离不足

**现状：** AI agent（Claude Code / Codex）在 `generated_sites/<site_id>/` 目录下执行，但没有文件系统沙箱。Codex 使用了 `--dangerously-bypass-approvals-and-sandbox`（第 613 行），这意味着 agent 可以：
- 读取其他 site 的文件（`../other_site_id/`）
- 读取容器内的环境变量、数据库凭据
- 通过 `docker.sock`（已挂载）操纵宿主机容器

**预警信号：** AI 生成的代码中引用了 `../` 路径或读取了 `/etc/` 下的文件。

**防范策略：**
- 每个 AI 任务在独立容器中执行（通过 Docker API 动态创建），只挂载该 site 目录
- 短期内：至少移除 celery-worker 容器的 `docker.sock` 挂载
- 使用 Linux namespace 或 `unshare` 限制 agent 进程的文件系统可见范围
- Codex 的 `--dangerously-bypass-approvals-and-sandbox` 在多用户场景下是不可接受的安全风险

**阶段：** Phase 1（安全加固），Phase 3（容器化沙箱）

### 2.4 `generated_sites/` 无备份导致 AI 改坏代码无法恢复

**现状：** AI 修改文件后会自动 `restart_site`，如果改坏了只能从 git history 恢复（前提是之前有 commit）。但 `run_develop_task` 完成后不会自动 commit（由 AI agent 决定是否 commit），可能出现 uncommitted 但已部署的状态。

**预警信号：** 用户发现网站坏了，但 git log 显示只有初始 commit。

**防范策略：**
- 任务开始前自动 `git stash` 或创建 checkpoint commit（`git add -A && git commit -m "pre-task checkpoint"`）
- 任务成功后自动 commit（`git add -A && git commit -m "Task {task_id} completed"`）
- 任务失败后提供一键 rollback 到上一个 checkpoint 的 API
- 在 Skill 的 prompt 中要求 AI 在完成修改后执行 git commit

**阶段：** Phase 2

---

## 3. Automated Browser Testing (Playwright)

### 3.1 Playwright 在容器中的 Chromium 资源问题

**现状：** `smoke_test_task` 在 Celery worker 容器中执行 `node playwright_smoke_runner.mjs`。Chromium 每次启动约消耗 200-500MB 内存。Worker concurrency 为 4（`-c 4`），4 个并发测试会消耗 2GB+ 内存。

**预警信号：** 测试任务频繁出现 `OOM killed` 或 Chromium crash，容器被 Docker 强制重启。

**防范策略：**
- 为测试任务单独配置 Celery queue 和 worker，限制并发数为 1-2
- 设置容器内存限制（`mem_limit`）并在 Playwright 配置中限制 `--disable-dev-shm-usage`
- 使用 Playwright 的 browser context 复用（`browser.newContext()` 而非每次 `launch()`）
- 增加 `/dev/shm` 大小（`shm_size: '2gb'` 在 docker-compose 中）

**阶段：** Phase 3（测试功能）

### 3.2 测试 base_url 解析逻辑脆弱

**现状：** `run_playwright_smoke_task` 中 base_url 的确定逻辑（第 760-762 行）：先看 payload，再看环境变量，再 hardcode `http://127.0.0.1:8080`。容器内检测 `/.dockerenv` 后替换端口。这套逻辑在跨容器网络中容易失败——worker 容器访问 site 进程需要用 `main-service:port` 而非 `127.0.0.1:port`。

**预警信号：** 测试任务总是报 `ERR_CONNECTION_REFUSED`，但手动测试 preview 正常。

**防范策略：**
- site 的预览 URL 应该从 Site 模型中获取（`site.internal_url` 或根据 port 构造 `http://main-service:{port}`）
- 不要在测试代码中硬编码 URL 替换逻辑
- 使用 Docker network alias 确保 worker 可以访问 main-service 容器内的 site 进程

**阶段：** Phase 3

### 3.3 Flaky Tests 导致 AI 编码循环

**现状：** 设计要求 "AI 编码完成后自动生成 Playwright 测试用例"。如果生成的测试本身 flaky（timing issues、animation waits），AI 会进入 "修代码 -> 测试失败 -> 再修 -> 再失败" 的循环，每次循环消耗 API tokens。

**预警信号：** 同一任务链连续失败 3 次以上，每次失败原因不同但都是 timing 相关。

**防范策略：**
- 生成测试时在 prompt 中明确要求使用 `waitForSelector`、`waitForLoadState` 等 Playwright best practices
- 为自动化测试设置最大重试次数（2-3 次），超过后标记为 "需人工检查" 而非继续 AI 修复
- 测试结果中区分 "确定性失败" 和 "可能 flaky"（通过分析 error message pattern）
- 使用 Playwright 的 `--retries` 参数在测试级别做简单重试

**阶段：** Phase 3

### 3.4 截图和 trace 文件累积耗尽磁盘

**现状：** `artifacts_dir` 在 `/shared/task_artifacts/{task_id}/` 下，没有清理策略。Playwright trace + 截图每次测试约 5-20MB，千次测试后累积到 GB 级别。

**预警信号：** `/shared` 分区使用率持续上升，最终导致所有文件写入失败。

**防范策略：**
- 实现定期清理 cron job（Celery beat task），删除 N 天前的 artifacts
- 设置 artifacts 目录的磁盘配额
- 对于成功的测试只保留最近一份截图
- 上传关键 artifacts 到 MinIO（已部署），本地只保留最近任务的

**阶段：** Phase 3

---

## 4. Skill-Based Deployment Systems

### 4.1 部署凭据明文存储

**现状：** `SiteDeployConfig` 模型中 `login_password` 存储为 `Text` 类型（明文）。`UserLLMProvider.api_key` 同样是明文 `Text`。数据库备份、日志、或任何有 DB 读权限的人都能看到所有凭据。

**预警信号：** 安全审计发现数据库中可直接读取密码和 API Key。

**防范策略：**
- 使用 `cryptography.fernet` 或 `age` 对敏感字段加密存储，应用层解密
- 最低要求：确保数据库连接使用 TLS，备份加密
- API 返回时对 key/password 做脱敏处理（只返回 `****last4`）
- 长期：使用 Vault 或 KMS 管理凭据

**阶段：** Phase 1（安全）

### 4.2 部署步骤缺乏幂等性

**现状：** `deploy_task` 当前只做 `restart_site`（本地部署）。但 Apollo 部署路径（第 31-37 行）只设置了 SUCCESS 状态而没有实际实现。当实现真正的部署 Skill（推镜像、调 K8s API）时，如果任务中途失败重试，可能导致：
- 同一镜像被 push 两次（浪费带宽但无害）
- 同一个 deployment 被创建两次（导致副本数翻倍）
- 登录获取的 token 过期，后续步骤全部失败

**预警信号：** 部署重试后出现两个相同应用的 pod，或 token 过期导致级联失败。

**防范策略：**
- 每个 Skill step 设计为幂等操作：先查再创建（`get-or-create` 模式）
- 部署 token 获取作为独立步骤，失败后只重试该步骤
- 为每次部署生成唯一的 deployment label/tag，用于去重
- 实现部署状态机：每步完成后持久化进度，重试时从上次失败的步骤开始

**阶段：** Phase 4（部署 Skill 实现）

### 4.3 Rollback 机制缺失

**现状：** 部署成功后没有任何回滚能力。如果新版本有 bug，用户只能手动操作目标平台回滚。

**预警信号：** 用户部署后发现问题，但在平台内找不到回滚按钮，只能去 K8s 控制台操作。

**防范策略：**
- 每次部署前记录 "上一个已知良好版本"（镜像 tag 或 git commit）
- Skill 定义中增加 `rollback_steps` 字段
- 部署后保留 "上一版本" 信息在 `SiteDeployConfig` 中
- 实现一键 rollback API，调用对应 Skill 的 rollback 步骤

**阶段：** Phase 4

### 4.4 Skill 内容被注入恶意指令

**现状：** Skill 内容（`skill.content`）直接拼接进 AI prompt（`task_service.py:546-547`）。如果用户导入了恶意 Skill（通过 `import_skill` 从 skills.sh），其内容可能包含 prompt injection 攻击，让 AI agent 执行非预期操作（如删除文件、读取敏感信息）。

**预警信号：** 导入的 Skill 内容包含类似 "ignore previous instructions" 的文本。

**防范策略：**
- 导入 Skill 时做内容审查：标记包含可疑指令模式的 Skill
- Skill 内容在 prompt 中应使用明确的 delimiter（如 XML tag）隔离
- 限制 Skill 的字符数上限（避免 context window 被 Skill 内容填满）
- 显示 Skill 内容预览，让用户确认后再启用

**阶段：** Phase 2（Skill 机制完善）

---

## 5. Brownfield Integration (演进现有模型)

### 5.1 Site 到 Project + Repo 的模型迁移

**现状：** 系统中所有功能都围绕 `Site` 构建——任务绑定到 site_id，文件浏览绑定到 site_id，部署绑定到 site_id。引入 "Project" 概念后需要：
- 新增 `Project` 和 `Repo` 模型
- 所有 API 路由从 `/sites/{site_id}/tasks` 变为 `/projects/{project_id}/repos/{repo_id}/tasks`（或保持 `/sites/` 路由作兼容）
- 前端所有 store 和组件适配新 API

**预警信号：** 改了后端 API 但前端还在调旧路由，部分功能静默失败。

**防范策略：**
- API 版本化：新功能用 `/api/v3/projects/`，保留 `/api/v2/sites/` 不变
- 数据库迁移分两步：先加新表和 FK，再写 data migration 把现有 Site 转换为 "单 repo project"
- 前端和后端同步迁移，使用 feature flag 控制切换
- 绝不在一次 PR 中同时改模型、API、前端——拆成 3 个可独立合并的 PR

**阶段：** Phase 2

### 5.2 Alembic 迁移在生产环境中的风险

**现状：** 使用 SQLAlchemy + Alembic 做 schema 迁移。当模型改动较大时（如新增多个表、修改外键），如果迁移脚本有 bug，可能导致数据库处于半迁移状态。

**预警信号：** `alembic upgrade head` 执行一半报错，部分表已创建部分未创建，回滚也失败。

**防范策略：**
- 每次迁移前备份数据库（`pg_dump`）
- 在 CI 中用生产数据快照测试迁移脚本
- 大型迁移拆成多个小迁移，每个迁移单独可逆
- 不使用 `autogenerate` 盲目生成迁移——手动审查每个迁移文件

**阶段：** 所有阶段

### 5.3 Service Singleton 的状态泄露

**现状：** `site_service`、`task_service`、`deploy_service` 都是模块级 singleton。`site_service` 中的 `_SITE_PROCESSES` 字典在内存中跟踪运行中的 site 进程。如果 main-service 容器重启，这个字典清空，但 site 的子进程可能仍在运行（因为 `start_new_session=True`），导致端口占用和孤儿进程。

**预警信号：** 容器重启后 site 显示 "stopped" 但端口被占用，启动失败报 `Address already in use`。

**防范策略：**
- 启动时扫描所有 RUNNING 状态的 site，检查端口是否被占用，如果是则 kill 孤儿进程
- 将进程 PID 持久化到数据库或文件，重启后用于清理
- 使用 supervisor 或 systemd 管理 site 子进程而非裸 `Popen`

**阶段：** Phase 2（稳定性）

### 5.4 WebSocket 消息格式变更破坏前端

**现状：** `websocket_service.py` 通过 Redis pub/sub 推送 `{"type": "log", "data": {...}}` 和 `{"type": "status", ...}` 消息。前端 store 直接解析这些 JSON 结构。如果后端添加新字段或改变结构，已连接的前端客户端会出错。

**预警信号：** 部署新后端后，已打开的前端页面日志面板不再更新。

**防范策略：**
- WebSocket 消息增加 `version` 字段
- 前端解析时对缺失字段做 fallback
- 后端在添加新消息类型时保持旧类型不变（只增不改）
- 关键变更时前端显示 "页面需要刷新" 提示

**阶段：** 所有阶段

### 5.5 SQLite JSON 列在 PostgreSQL 上的行为差异

**现状：** 模型使用 `SQLITE_JSON`（`from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON`），如 `site.py:32`、`skill.py:19`。但生产环境使用 PostgreSQL。SQLite 的 JSON 和 PostgreSQL 的 JSONB 在索引、查询语法、NULL 处理上有差异。测试容器使用 SQLite（`docker-compose.yml:234`），可能让 bug 通过测试但在生产中暴露。

**预警信号：** 测试全通过但生产环境出现 JSON 字段相关的查询错误。

**防范策略：**
- 将所有 `SQLITE_JSON` 替换为 SQLAlchemy 的跨数据库 `JSON` 类型
- 测试环境也使用 PostgreSQL（docker-compose 中 test service 连接 postgres）
- 对 JSON 字段的查询使用 SQLAlchemy ORM 方法而非原生 SQL

**阶段：** Phase 1（基础代码修复）

---

## 总结：按阶段分类的关键陷阱

| 阶段 | 必须解决的陷阱 |
|------|---------------|
| **Phase 1** | API Key 泄露 (1.1)、Token 上限 (1.2)、命令注入 (1.4)、凭据明文 (4.1)、SQLite/PG 差异 (5.5) |
| **Phase 2** | 并发 Git 冲突 (2.2)、Site->Project 迁移 (5.1, 2.1)、代码回滚 (2.4)、Skill 注入 (4.4)、孤儿进程 (5.3) |
| **Phase 3** | Playwright 资源 (3.1)、base_url 解析 (3.2)、Flaky tests (3.3)、Artifact 清理 (3.4) |
| **Phase 4** | 部署幂等性 (4.2)、Rollback 机制 (4.3) |
| **全阶段** | Alembic 迁移安全 (5.2)、WebSocket 兼容 (5.4)、文件系统隔离 (2.3) |

---

*Pitfalls analysis: 2026-04-23*
