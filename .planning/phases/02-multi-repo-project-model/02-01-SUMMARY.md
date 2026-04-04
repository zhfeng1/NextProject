# Plan 02-01 Summary: Project + ProjectRepo 数据模型与 Alembic 迁移

## Outcome: COMPLETED

所有 6 个任务已按顺序完成，每个任务独立提交。

## Tasks Completed

| Task | Title | Commit | Status |
|------|-------|--------|--------|
| 02-01-01 | 创建 Project 模型文件 | 9580a36 | DONE |
| 02-01-02 | Site 模型添加 project_id FK | 6aa4784 | DONE |
| 02-01-03 | TaskType 枚举添加 CLONE_REPO | 9a8f4dc | DONE |
| 02-01-04 | 注册 Project 模型到 __init__.py | f292301 | DONE |
| 02-01-05 | 创建 Alembic 迁移脚本 | 7163567 | DONE |
| 02-01-06 | 编写 Project 模型单元测试 | 80296ae | DONE |

## What Changed

### New Files
- `backend/models/project.py` — Project 数据模型（name, description, org_id, owner_id, deleted_at）
- `backend/alembic/versions/20260423_0002_add_projects.py` — Alembic 迁移：建表 + 数据迁移 + 文件系统迁移
- `backend/tests/test_projects.py` — Project 单元测试（4 个测试用例）

### Modified Files
- `backend/models/site.py` — 添加 `project_id` 可空 FK 指向 `projects.id`（CASCADE 删除）
- `backend/models/enums.py` — `TaskType` 枚举添加 `CLONE_REPO = "clone_repo"`
- `backend/models/__init__.py` — 注册 `Project` 模型导入和 `__all__` 导出

## Verification Results

- `test_site_without_project_id_still_works` — PASSED（向后兼容验证）
- `test_sites.py` 全部 11 个测试 — PASSED（现有功能无回归）

## Decisions

| Decision | Rationale |
|----------|-----------|
| 使用 mixins.py 的 UUIDPrimaryKeyMixin（String(36)）而非 base.py 版本 | 与 Site 模型保持一致，避免 UUID 类型不兼容 |
| project_id 设为 nullable | 保持向后兼容，现有 Site 可以没有关联 Project |
| 迁移中用 copy-verify-delete 策略 | 降低文件系统迁移丢失数据风险（T-02-04 缓解） |
| 数据迁移用 sa.text() 参数化查询 | 防止 SQL 注入（T-02-01 缓解） |

## Risks Mitigated

- T-02-02: 数据迁移在事务中执行 + project_id 可空
- T-02-04: 文件系统迁移用 copytree + exists 验证 + rmtree
