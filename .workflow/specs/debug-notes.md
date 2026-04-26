---
title: "Debug Notes"
readMode: optional
priority: medium
category: debug
keywords:
  - debug
  - issue
  - workaround
  - root-cause
  - gotcha
---
# Debug Notes

Known issues, debugging tips, and root cause records.
Add entries with: `/spec-add debug <description>`

## Entries

- [2026-04-20 14:21] Frontend TypeScript is not yet strict and several files use `@ts-nocheck`; type-related regressions are easier to introduce in those areas.
- [2026-04-20 14:21] Backend currently carries both legacy APIs and `/api/v2`, so behavior drift between the two surfaces should be checked when modifying shared flows.
