# Programming Tool Adapter

One image is built four times with `TOOL_ID=codex`, `claude_code`, `codebuddy`, or
`opencode`. Their default ports are `8090`, `8091`, `8092`, and `8093`; `PORT` can
override them. `/health` is intentionally public for Docker health checks; every
other endpoint requires `X-Adapter-Token` matching the
`PROGRAMMING_TOOL_ADAPTER_TOKEN` environment variable (`ADAPTER_TOKEN` remains a
compatibility alias).

## Runtime API

- `GET /health`
- `GET /v1/metadata`
- `POST /v1/runs` (`application/x-ndjson` response)
- `POST /v1/runs/{task_id}/cancel`

The run body is:

```json
{
  "task_id": "task-id",
  "cwd": "/generated_sites/project/.worktree/branch",
  "prompt": "Implement the task",
  "task_mode": "develop",
  "model": {
    "format": "responses",
    "base_url": "https://provider.example/v1",
    "api_key": "secret",
    "model": "model-name",
    "provider_name": "Project provider"
  },
  "mcp_servers": [],
  "timeout_seconds": 3600
}
```

Only `run_started`, `display_delta`, `usage`, `diagnostic`, and `run_finished`
events are emitted. CLI output is stored below `TASK_ARTIFACTS_ROOT`; provider API
keys are only placed in the short-lived process environment. Runtime config lives
below `ADAPTER_RUNTIME_ROOT`, which must be mounted as tmpfs in Compose.

Codex keeps `/oauth/*` and `/mcp/status`. Claude Code keeps `/auth/*` and
`/mcp/status`. These compatibility endpoints also require the adapter token.
