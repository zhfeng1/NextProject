---
title: "Validation Rules"
readMode: required
priority: high
category: validation
keywords:
  - validation
  - verification
  - acceptance
  - criteria
  - check
---
# Validation Rules

## Verification Criteria
- Validate the affected API, UI, or task flow with the project’s existing tooling before claiming completion
- Prefer checking both success path and one likely failure/edge path for user-facing changes
- For backend changes, run targeted pytest coverage where possible
- For frontend changes, verify visible behavior, not only type-check/build status

## Acceptance Standards
- The resulting behavior must remain fast enough for iteration without dropping quality safeguards
- User-facing workflows should be understandable by both technical and non-technical users
- Changes should preserve deployment and operational realism; do not hide problems behind mocks or skipped verification unless explicitly justified

## Manual Additions

