from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|CERTIFICATE)-----.*?-----END [A-Z0-9 ]*(?:PRIVATE KEY|CERTIFICATE)-----",
    re.IGNORECASE | re.DOTALL,
)
_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]{8,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd|pwd|authorization)\b"
    r"\s*(?:=|:|\s)\s*)([\"']?)([^\s,;\"'}\]]{4,})([\"']?)"
)
_ENV_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|AUTHORIZATION)[A-Z0-9_]*=)([^\s]+)"
)
_URL_USERINFO_RE = re.compile(r"(?i)(https?://)([^/@\s]+)@")
_URL_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|key|token|access_token|signature|sig|secret|password)=)([^&#\s]+)"
)


def redact_execution_text(value: str) -> str:
    """Apply a second redaction pass before private traces reach the browser."""
    text = str(value or "")
    text = _PEM_RE.sub("[REDACTED_PEM]", text)
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    text = _JWT_RE.sub("[REDACTED_JWT]", text)
    text = _OPENAI_KEY_RE.sub("[REDACTED]", text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(r"\1\2[REDACTED]\4", text)
    text = _ENV_ASSIGNMENT_RE.sub(r"\1[REDACTED]", text)
    text = _URL_USERINFO_RE.sub(r"\1[REDACTED]@", text)
    return _URL_QUERY_SECRET_RE.sub(r"\1[REDACTED]", text)


def read_execution_trace(
    path: Path,
    *,
    after_seq: int = 0,
    limit: int = 200,
) -> tuple[list[dict[str, Any]], bool]:
    if not path.exists() or not path.is_file() or path.is_symlink():
        return [], False

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(item, dict):
                continue
            seq = int(item.get("seq") or 0)
            if seq <= after_seq:
                continue
            content = item.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, sort_keys=True)
            events.append({
                "source": "adapter",
                "seq": seq,
                "ts": str(item.get("ts") or ""),
                "level": str(item.get("level") or "INFO").upper(),
                "kind": str(item.get("kind") or "cli_output"),
                "content": redact_execution_text(content),
            })
            if len(events) > limit:
                break
    has_more = len(events) > limit
    return events[:limit], has_more


__all__ = ["read_execution_trace", "redact_execution_text"]

