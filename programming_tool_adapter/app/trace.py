from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_SK_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE)
_PEM_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]+-----.*?-----END [A-Z0-9 ]+-----",
    re.DOTALL,
)
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b([A-Za-z_][A-Za-z0-9_]*(?:api[_-]?key|key|token|password|passwd|secret|auth|authorization|credential)[A-Za-z0-9_]*)"
    r"(\s*[:=]\s*)(['\"]?)([^\s,'\";\]\}&?#]+)(['\"]?)",
)
_SENSITIVE_JSON_PATTERN = re.compile(
    r'(?i)(["\'](?:api[_-]?key|token|password|passwd|secret|auth|authorization|credential)["\']\s*:\s*)'
    r'(["\'])(.*?)(\2)',
)
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SENSITIVE_QUERY_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "key",
    "password",
    "passwd",
    "secret",
    "signature",
    "sig",
    "token",
}
_SENSITIVE_FIELD_MARKERS = (
    "apikey",
    "authorization",
    "credential",
    "password",
    "passwd",
    "secret",
)


class SensitiveDataRedactor:
    def __init__(self, sensitive_values: Iterable[str] = ()) -> None:
        self._sensitive_values: tuple[str, ...] = ()
        self.add_sensitive_values(sensitive_values)

    def add_sensitive_values(self, values: Iterable[str]) -> None:
        combined = {*self._sensitive_values, *(str(value) for value in values if str(value))}
        self._sensitive_values = tuple(sorted(combined, key=len, reverse=True))

    @staticmethod
    def _is_sensitive_field(name: str) -> bool:
        raw_name = str(name)
        normalized = re.sub(r"[^a-z0-9]", "", raw_name.lower())
        if normalized in {"token", "key", "auth"}:
            return True
        if any(marker in normalized for marker in _SENSITIVE_FIELD_MARKERS):
            return True
        separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw_name)
        parts = [part.lower() for part in re.split(r"[^A-Za-z0-9]+", separated) if part]
        return bool(parts and parts[-1] in {"token", "key", "auth"})

    @staticmethod
    def _redact_url(match: re.Match[str]) -> str:
        raw_url = match.group(0)
        trailing = ""
        while raw_url and raw_url[-1] in ".,);]}:":
            trailing = raw_url[-1] + trailing
            raw_url = raw_url[:-1]
        try:
            parsed = urlsplit(raw_url)
            hostname = parsed.hostname or ""
            port = parsed.port
        except ValueError:
            return "[REDACTED:URL]" + trailing
        if not hostname:
            return "[REDACTED:URL]" + trailing
        netloc = hostname
        if ":" in hostname and not hostname.startswith("["):
            netloc = f"[{hostname}]"
        if port is not None:
            netloc += f":{port}"
        query = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            query.append((key, "[REDACTED]" if key.lower() in _SENSITIVE_QUERY_NAMES else value))
        sanitized = urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(query, doseq=True), ""))
        return sanitized + trailing

    def redact_text(self, text: str) -> str:
        redacted = str(text)
        for value in self._sensitive_values:
            redacted = redacted.replace(value, "[REDACTED]")
        redacted = _PEM_PATTERN.sub("[REDACTED:PEM]", redacted)
        redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", redacted)
        redacted = _JWT_PATTERN.sub("[REDACTED:JWT]", redacted)
        redacted = _SK_PATTERN.sub("[REDACTED:API_KEY]", redacted)
        redacted = _SENSITIVE_JSON_PATTERN.sub(r"\1\2[REDACTED]\2", redacted)
        redacted = _SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1\2\3[REDACTED]\5", redacted)
        return _URL_PATTERN.sub(self._redact_url, redacted)

    def redact(self, value: Any, *, field_name: str = "") -> Any:
        if isinstance(value, dict):
            return {
                str(key): self.redact(
                    child,
                    field_name=str(key),
                )
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [self.redact(child) for child in value]
        if isinstance(value, tuple):
            return [self.redact(child) for child in value]
        if isinstance(value, str):
            if field_name and self._is_sensitive_field(field_name):
                return "[REDACTED]"
            return self.redact_text(value)
        return value


class ExecutionTraceWriter:
    def __init__(self, path: Path, sensitive_values: Iterable[str] = ()) -> None:
        self.path = path
        self.redactor = SensitiveDataRedactor(sensitive_values)
        self.seq = 0
        self.file = self._open_private(path)

    @staticmethod
    def _open_private(path: Path) -> TextIO:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            return os.fdopen(descriptor, "w", encoding="utf-8")
        except BaseException:
            os.close(descriptor)
            raise

    def add_sensitive_values(self, values: Iterable[str]) -> None:
        self.redactor.add_sensitive_values(values)

    def write(self, kind: str, content: Any, *, level: str = "INFO") -> dict[str, Any]:
        self.seq += 1
        event = {
            "seq": self.seq,
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "kind": str(kind),
            "level": str(level).upper(),
            "content": self.redactor.redact(content),
        }
        self.file.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.file.flush()
        return event

    def close(self) -> None:
        if not self.file.closed:
            self.file.close()

    def __enter__(self) -> ExecutionTraceWriter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
