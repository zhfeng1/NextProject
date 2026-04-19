---
status: complete
phase: 01-security-hardening
source: [SUMMARY.md]
started: 2026-04-23T15:00:00Z
updated: 2026-04-23T16:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. API Key 加密存储
expected: 在设置页面编辑 LLM Provider，输入 API Key 保存后刷新。API Key 显示为脱敏格式（sk-proj-ab******90），不显示明文，长度与原始 key 一致。
result: pass

### 2. API Key 覆盖更新
expected: 在 Provider 设置中，已有脱敏 Key 时留空"API Key"字段并保存，原 Key 不被覆盖。输入新 Key 保存后，新 Key 生效（脱敏显示变化）。
result: pass

### 3. 模型连通性验证
expected: 在 Provider 设置页，已配置模型旁显示"验证"按钮。点击后按钮显示加载状态，验证成功显示绿色提示，验证失败显示错误信息。
result: pass

### 4. SSRF 防护验证
expected: 在 Provider 设置中，将 base_url 设为内网地址，调用 verify-model 或 fetch-models 端点时返回中文错误提示，拒绝访问内网地址。
result: pass

### 5. 并发任务 Redis 锁
expected: 对同一个站点同时触发两个 AI 编码任务，第二个任务应排队等待。
result: skipped
reason: 需要完整 AI 编码流程才能测试

### 6. FERNET_KEY 配置
expected: docker-compose.yml 中 main-service 和 celery-worker 均有 FERNET_KEY 环境变量。.env.example 中有 FERNET_KEY 条目和生成说明。
result: pass

## Summary

total: 6
passed: 4
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps
