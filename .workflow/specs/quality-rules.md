---
title: "Quality Rules"
readMode: required
priority: medium
category: execution
keywords:
  - quality
  - rule
  - enforcement
  - standard
---
# Quality Rules

Project-specific quality rules and enforcement criteria.
Add entries with: `/workflow:specs-add rule <description>`

## Format

Each entry follows: `- [{YYYY-MM-DD HH:mm}] <description>`

## Entries

- [2026-04-20 14:21] 质量不能为速度让路；任何提速方案都应保留测试、可回滚性和基本可维护性。
- [2026-04-20 14:21] 修改应尽量小而直接，优先沿用现有架构与模式，避免无关重构。
- [2026-04-20 14:21] 影响用户主链路的改动必须优先考虑需求 → 生成/调整 → 测试 → 部署的完整闭环体验。
- [2026-04-20 14:21] 易用性需要面向程序员、项目经理和普通用户，不以纯工程师视角设计交互。
