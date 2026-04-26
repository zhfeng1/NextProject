---
title: "Review Standards"
readMode: required
priority: medium
category: review
keywords:
  - review
  - checklist
  - gate
  - approval
  - standard
---
# Review Standards

## Review Checklist
- Does the change improve or preserve the main product loop: requirement → implementation/adjustment → test → deploy?
- Is the change small, direct, and consistent with existing code patterns?
- Are security-sensitive values and operational side effects handled carefully?
- Are legacy and `/api/v2` interactions considered where relevant?
- Is the UX understandable for non-expert users when touching user-facing flows?

## Quality Gates
- No obvious regression in core site/task/auth/deploy flows
- New or changed behavior has matching verification proportional to risk
- Documentation/spec updates are made when they change future planning assumptions

## Manual Additions

