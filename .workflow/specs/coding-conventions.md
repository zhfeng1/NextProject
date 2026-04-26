---
title: "Coding Conventions"
readMode: required
priority: high
category: execution
keywords:
  - style
  - naming
  - import
  - pattern
  - convention
---
# Coding Conventions

Auto-generated from project analysis. Update manually as patterns evolve.

## Formatting
- Indentation: Frontend uses 2 spaces; backend Python uses 4 spaces
- Line length: not explicitly configured
- Trailing commas: mixed, follow surrounding file style
- Semicolons: generally omitted in frontend TypeScript/Vue files

## Naming
- Variables/functions: camelCase in TypeScript/Vue, snake_case in Python
- Classes/types: PascalCase in TypeScript types/components, PascalCase for Python classes
- Constants: UPPER_SNAKE_CASE in Python, mixed in frontend but prefer existing local style
- Files: Vue components use PascalCase, many TS utility/api files use lower-case or camelCase, Python files use snake_case

## Imports
- Style: named imports are common in frontend; Python imports grouped by stdlib / third-party / local modules
- Path aliases: frontend uses `@/*` → `src/*`
- Order: prefer built-in, external, internal, then relative imports; follow existing file order when editing

## Patterns
- Frontend uses Vue 3 Composition API with `<script setup lang="ts">`
- API calls are centralized under `frontend/src/api/`
- Frontend state lives in Pinia stores under `frontend/src/stores/`
- Backend follows `api -> services -> models/schemas/core/utils` layering
- Backend service modules expose singleton service instances
- Match existing file style rather than normalizing unrelated files during feature work

## Manual Additions
- Prefer minimal changes and reuse existing patterns before introducing abstractions
