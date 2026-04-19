---
phase: 1
plan: 2
status: complete
started: 2026-04-23T00:00:00
completed: 2026-04-23T13:16:00
---

# Plan 01-02: API Key 连通性验证端点

**新增 verify-model 端点，支持对已保存 provider 的模型发送轻量验证请求，前端添加验证按钮。**

## Performance
- **Tasks:** 3/3 complete

## Accomplishments
- POST /providers/verify-model 端点：支持 Messages/Responses/Chat Completions 三种格式
- Key 在后端解密，前端不传明文
- SSRF 防护：仅允许 http/https scheme
- 前端 verifyModel API 方法 + 验证按钮 UI

## Task Commits
1. **Task 2.1: verify-model 后端端点** — `dd12033` (feat)
2. **Task 2.2: 前端 verifyModel API** — `467a10e` (feat)
3. **Task 2.3: 前端验证按钮** — `631d02e` (feat)

## Files Created/Modified
- `backend/api/v2/providers.py` — verify-model 端点
- `frontend/src/api/providers.ts` — verifyModel API 方法
- `frontend/src/views/Settings/Account.vue` — 验证状态 + 按钮 UI

## Self-Check: PASSED
All 18 acceptance criteria verified.
