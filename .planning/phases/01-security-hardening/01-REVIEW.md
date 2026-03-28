# Security Hardening Review

**Phase:** 01-security-hardening
**Date:** 2026-04-23
**Depth:** standard

---

## Summary

API Key 加密存储已基本落地（Fernet），前端脱敏、后端加解密链路完整。主要风险集中在 SSRF 防护不足、`fetch-models` 端点接受用户任意 URL 且直接传入明文 API Key、Docker Socket 挂载、以及默认凭据硬编码等方面。

---

## Findings

### CRITICAL

#### C1 — `fetch-models` 端点：无 SSRF 防护 + 明文 API Key 泄露风险
- **File:** `backend/api/v2/providers.py:193-214`
- **Issue:** `/providers/fetch-models` 接受用户提供的任意 `base_url` 和明文 `api_key`，且没有任何 SSRF 防护（不像 `verify-model` 至少检查了 scheme）。攻击者可以：
  1. 指定内部网络地址（如 `http://postgres:5432`、`http://redis:6379`、`http://169.254.169.254/`）进行 SSRF 探测
  2. 将 `base_url` 指向攻击者控制的服务器以窃取用户输入的 `api_key`
- **Recommendation:**
  - 添加与 `verify-model` 相同的 scheme 检查
  - 实现内网 IP 黑名单（禁止 `127.0.0.0/8`、`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16` 等）
  - 考虑不在此端点接受明文 `api_key`，而是引用已保存的 provider ID 从数据库解密获取

#### C2 — `verify-model` 端点：SSRF 防护不完整
- **File:** `backend/api/v2/providers.py:128-130`
- **Issue:** 只检查了 `http://` 和 `https://` scheme，但未禁止请求内网 IP 和容器内部服务名（如 `http://redis:6379`、`http://postgres:5432`）。攻击者可探测内部服务。
- **Recommendation:** 实现 DNS 解析后的 IP 黑名单校验，或使用白名单模式仅允许已知公网 API 域名。

### HIGH

#### H1 — Docker Socket 挂载暴露容器逃逸风险
- **File:** `docker-compose.yml:65-66, 135-136`
- **Issue:** `main-service` 和 `celery-worker` 均挂载了 `/var/run/docker.sock`。拥有 Docker Socket 访问权限等同于宿主机 root 权限。如果任一服务被攻破（尤其 Celery worker 执行用户提供的命令），攻击者可完全控制宿主机。
- **Recommendation:**
  - 评估是否真正需要 Docker Socket，若仅用于子站点管理，考虑使用 Docker API over TCP（受限访问）或专用 sidecar
  - 如必须挂载，使用 `docker.sock` 代理（如 Tecnativa/docker-socket-proxy）限制可调用的 API

#### H2 — Celery Worker 执行用户提供的命令存在命令注入风险
- **File:** `backend/services/task_service.py:597, 656-664`
- **Issue:** 当 `payload` 中提供了 `command` 字段时，直接使用 `shlex.split(command_text)` 拆分后通过 `asyncio.create_subprocess_exec` 执行。虽然 `exec` 模式比 `shell=True` 安全，但 `command` 来自用户输入（通过 API payload），仍可执行任意系统命令。
- **Recommendation:**
  - 如果 `command` 字段仅用于内部/管理员使用，需在 API 层校验用户权限（superuser only）
  - 考虑移除直接命令执行能力，改为只接受预定义的 provider 命令

#### H3 — 默认管理员凭据硬编码
- **File:** `backend/core/config.py:88-89`
- **Issue:** `default_admin_email = "admin@example.com"` 和 `default_admin_password = "admin123456"` 硬编码在配置中。如果首次启动时自动创建管理员账户，且用户未修改默认值，系统即暴露已知凭据。
- **Recommendation:** 在生产环境启动时检测是否使用默认密码并强制要求修改，或要求通过环境变量设置。

#### H4 — API Key 通过环境变量传递给子进程
- **File:** `backend/services/task_service.py:648`
- **Issue:** Claude Code provider 将 `ANTHROPIC_API_KEY` 通过环境变量传递。环境变量可通过 `/proc/<pid>/environ` 被同容器内其他进程读取，且可能出现在进程列表、core dump 中。代码注释说明了原因（Claude CLI 限制），但这仍是一个风险点。
- **Recommendation:** 已有注释说明此为 accepted risk。建议至少确保 worker 容器的 `/proc` 挂载了 `hidepid=2`，并在子进程结束后立即清理。

### MEDIUM

#### M1 — Alembic 迁移 downgrade 静默吞异常
- **File:** `backend/alembic/versions/20260423_0001_encrypt_api_keys.py:60-61`
- **Issue:** `downgrade()` 中 `except Exception: pass` 静默跳过解密失败的行。如果 FERNET_KEY 不匹配，数据会保持加密状态但不报告任何错误，可能导致数据丢失而不自知。
- **Recommendation:** 至少记录 warning 日志，最好收集失败计数并在最后报告。

#### M2 — 加密检测依赖 magic prefix
- **File:** `backend/alembic/versions/20260423_0001_encrypt_api_keys.py:35, 53`
- **Issue:** 使用 `api_key.startswith("gAAAAA")` 检测是否已加密。Fernet token 确实以 `gAAAAA` 开头，但如果用户的明文 API Key 恰好以此开头，会被跳过而不加密。
- **Recommendation:** 可以在数据库中增加 `is_encrypted` 标志列，或使用已知前缀包装（如 `enc:` + ciphertext）来避免歧义。

#### M3 — Redis 连接未使用 TLS
- **File:** `docker-compose.yml:70-71`, `backend/core/config.py:32`
- **Issue:** Redis 连接使用 `redis://` 而非 `rediss://`，密码在网络中明文传输。在容器网络内风险较低，但如果 Redis 暴露到外部或跨主机部署则有泄露风险。
- **Recommendation:** 当前容器内部署可接受，但文档中应注明生产环境多节点部署时需启用 TLS。

#### M4 — `.env.example` 包含可直接使用的默认密码
- **File:** `.env.example:2, 8, 14-15, 24-25`
- **Issue:** 默认密码（`nextproject2025`、`redis2025`、`minioadmin2025`、`admin2025`）过于容易被直接用于生产环境。`SECRET_KEY` 和 `FERNET_KEY` 有占位符要求替换（好），但其他凭据有实际可用的默认值。
- **Recommendation:** 将所有密码字段改为 `<CHANGE_ME>` 占位符，或在 `start.sh` 中检测默认密码并警告。

#### M5 — CORS 配置允许通配符 methods 和 headers
- **File:** `backend/core/config.py:52-53`
- **Issue:** `cors_allow_methods = "*"` 和 `cors_allow_headers = "*"` 配合 `cors_allow_credentials = true` 使用。虽然 origins 有限制，但通配符 methods/headers 过于宽松。
- **Recommendation:** 将 methods 限制为 `GET,POST,PUT,DELETE,OPTIONS`，headers 限制为实际需要的值（如 `Content-Type, Authorization`）。

### LOW

#### L1 — 测试环境 FERNET_KEY 使用无效默认值
- **File:** `docker-compose.yml:241`
- **Issue:** `FERNET_KEY` 默认值 `dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nMTIzNDU=` 不是合法的 Fernet key（需要 32 字节 base64 url-safe 编码 = 44 字符）。测试可能因此跳过加密相关测试或使用 mock。
- **Recommendation:** 生成一个合法的测试用 Fernet key。

#### L2 — `celery-beat` 和 `flower` 缺少 `FERNET_KEY`
- **File:** `docker-compose.yml:170-177, 179-195`
- **Issue:** `celery-beat` 和 `flower` 服务有 `SECRET_KEY` 但缺少 `FERNET_KEY`。如果 Settings 加载时校验 `FERNET_KEY`，这些服务可能启动失败。
- **Recommendation:** 确认这些服务是否需要加载完整 Settings。如果不需要，可忽略；如果需要，应添加 `FERNET_KEY` 环境变量。

#### L3 — 前端 `fetchModels` 发送可能包含明文 API Key
- **File:** `frontend/src/views/Settings/Account.vue:91`, `frontend/src/api/providers.ts:35-36`
- **Issue:** 前端在调用 `fetchModels` 时将用户在输入框中填写的 API Key（可能是明文）通过 HTTP 发送。这与后端 `fetch-models` 端点的问题对应（见 C1）。
- **Recommendation:** 改为先保存 provider（密钥入库加密），再通过 provider ID 触发 fetch-models，避免明文 key 在请求中传输。

#### L4 — `provider_id` 路径参数未校验格式
- **File:** `backend/api/v2/providers.py:69, 96`
- **Issue:** `provider_id` 直接作为数据库主键查询，未校验是否为合法 UUID 格式。虽然 `db.get()` 对非法值只会返回 None（最终 404），不会导致注入，但加上格式校验是更好的实践。
- **Recommendation:** 可选优化，使用 UUID 类型替代 str。

---

## Architecture Notes

- **加密链路完整性：** `encrypt_api_key` -> DB 存储 -> `decrypt_api_key` -> 使用/脱敏 链路设计合理，前端始终看到 masked 值。
- **Redis Lock：** 使用 Lua 脚本的 owner-only release 模式正确，TTL 设计合理（task timeout + margin）。
- **Fernet Key 校验：** `config.py` 中的 `validate_fernet_key` 对长度和占位符进行了校验，启动时即可发现配置错误。
- **`docker-compose.yml` 中 SECRET_KEY/FERNET_KEY 使用 `${VAR:?error}`：** 强制要求设置，避免遗漏。

---

## Action Items (Priority Order)

1. **[CRITICAL]** 修复 `fetch-models` 端点 SSRF + API Key 泄露风险
2. **[CRITICAL]** 增强 `verify-model` SSRF 防护（内网 IP 黑名单）
3. **[HIGH]** 评估并限制 Docker Socket 访问
4. **[HIGH]** 限制或移除用户自定义 `command` 执行能力
5. **[HIGH]** 强制修改默认管理员密码
6. **[MEDIUM]** 改进迁移脚本的错误处理
7. **[MEDIUM]** 改进加密检测机制（避免 magic prefix）
8. **[MEDIUM]** 收紧 CORS 配置
9. **[LOW]** 修复测试 FERNET_KEY / celery-beat、flower 的环境变量
