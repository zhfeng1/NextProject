---
phase: 02
status: secured
threats_total: 9
threats_closed: 8
threats_open: 0
asvs_level: 1
audited: 2026-04-23
---

# Phase 02 Security Audit

## Threat Register

| ID | Severity | Status | Evidence |
|----|----------|--------|----------|
| T-02-01 | High | CLOSED | `site_service.py:217-226` — `resolve_site_path()` 使用 `Path.resolve()` 后调用 `target.relative_to(root)`，越界时抛出 `ValueError` → HTTP 400 |
| T-02-02 | High | CLOSED | `20260423_0002_add_projects.py:45` — `project_id` 列定义为 `nullable=True`；数据迁移在同一 Alembic `upgrade()` 事务内执行 |
| T-02-03 | Medium | ACCEPTED | `20260423_0002_add_projects.py:51-53` — FK 显式声明 `ondelete="CASCADE"`，属于有意设计，已在代码注释中记录 |
| T-02-04 | High | CLOSED | `site_service.py:192-202` — `clone_site_repository()` 使用列表形式 `subprocess.run(clone_command, ...)`，完全规避 shell 注入；凭据通过 `urllib.parse.quote` 编码嵌入 URL，不经 shell 展开 |
| T-02-05 | Medium | CLOSED | `project_service.py:76-84` — `get_project()` 检查 `owner_id == user_id OR org_id == org_id`，所有 CRUD 端点（list/get/update/delete/add_repo）均调用此方法；`projects.py:108,127` 的文件浏览端点同样先调用 `get_project()` |
| T-02-06 | Medium | CLOSED | `project_service.py:179-195` — `git_password` 调用 `encrypt_api_key()` (Fernet) 后以 `git_password_encrypted` 写入 payload，原始明文不落库；`clone_repo.py:44-45` 使用 `decrypt_api_key()` 解密；前端使用 Vue 默认模板转义，无 `v-html` |
| T-02-07 | Low | CLOSED | `router/index.ts:125-132` — `router.beforeEach` 守卫：`to.meta.requiresAuth && !authStore.isAuthenticated` 时重定向到 `/login`；所有受保护路由父级均设置 `meta: { requiresAuth: true }` |
| T-02-08 | Low | CLOSED | `read_site_file` 返回纯文本 `content` 字符串，由 Monaco Editor 以明文模式渲染，无 `v-html` 使用 |
| T-02-09 | Medium | CLOSED | `projects.py:111,129` — `list_repo_files` 和 `get_repo_file` 均检查 `str(site.project_id) != str(project_id)` → HTTP 404，防止跨项目访问 |

## Accepted Risks

- **T-02-03 (Data Loss — CASCADE delete)**：删除 Project 时级联软删除所有关联 Site（`delete_project` 方法）；数据库层 `ondelete="CASCADE"` 作为硬删除后备。属于有意设计行为，已在 migration 注释及服务层代码中明确记录。

## Audit Trail
- 2026-04-23: 初次安全审计，逐一核查源代码中的缓解措施实现情况，全部 8 项 mitigate 威胁均已确认 CLOSED，1 项 accept 威胁已确认符合设计意图。
