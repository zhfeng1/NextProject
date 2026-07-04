import json
import stat
from pathlib import Path

import pytest

from programming_tool_adapter.app.trace import ExecutionTraceWriter, SensitiveDataRedactor


def test_sensitive_data_redactor_covers_known_and_pattern_secrets() -> None:
    redactor = SensitiveDataRedactor(["known-provider-secret"])
    source = """known-provider-secret
Authorization: Bearer bearer-secret-value
eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature_value
sk-project-1234567890
api_key="inline-api-key"
DATABASE_PASSWORD=hunter2
https://alice:password@example.com/v1/responses?token=query-secret&safe=yes#private
-----BEGIN PRIVATE KEY-----
private-material
-----END PRIVATE KEY-----
"""

    result = redactor.redact_text(source)

    for secret in (
        "known-provider-secret",
        "bearer-secret-value",
        "signature_value",
        "sk-project-1234567890",
        "inline-api-key",
        "hunter2",
        "alice",
        "password@example.com",
        "query-secret",
        "private-material",
    ):
        assert secret not in result
    assert "Bearer [REDACTED]" in result
    assert "[REDACTED:JWT]" in result
    assert "[REDACTED:API_KEY]" in result
    assert "DATABASE_PASSWORD=[REDACTED]" in result
    assert "https://example.com/v1/responses?token=%5BREDACTED%5D&safe=yes" in result
    assert "[REDACTED:PEM]" in result


def test_sensitive_data_redactor_handles_nested_sensitive_fields() -> None:
    redactor = SensitiveDataRedactor()

    result = redactor.redact({
        "api_key": "not-a-prefixed-key",
        "access_token": "opaque-access-token",
        "privateKey": "opaque-private-key",
        "clientAuth": "opaque-auth-value",
        "authorization": "custom credential",
        "usage": {"input_tokens": 12, "output_tokens": 4, "monkey": "visible"},
    })

    assert result == {
        "api_key": "[REDACTED]",
        "access_token": "[REDACTED]",
        "privateKey": "[REDACTED]",
        "clientAuth": "[REDACTED]",
        "authorization": "[REDACTED]",
        "usage": {"input_tokens": 12, "output_tokens": 4, "monkey": "visible"},
    }


def test_sensitive_data_redactor_handles_malformed_url_port() -> None:
    redactor = SensitiveDataRedactor()

    result = redactor.redact_text("request failed: https://provider.example:invalid/v1?token=secret")

    assert result == "request failed: [REDACTED:URL]"
    assert "secret" not in result


def test_execution_trace_writer_is_incremental_private_and_redacted(tmp_path: Path) -> None:
    trace_path = tmp_path / "codex-execution-trace.ndjson"
    trace_path.write_text("old", encoding="utf-8")
    trace_path.chmod(0o644)

    writer = ExecutionTraceWriter(trace_path, ["first-secret"])
    first = writer.write("run_context", {"prompt": "first-secret", "model": "test-model"})
    writer.add_sensitive_values(["second-secret"])
    second = writer.write("raw_output", "Bearer second-secret", level="debug")
    writer.close()

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [event["seq"] for event in events] == [1, 2]
    assert first["seq"] == 1
    assert second["seq"] == 2
    assert all(event["ts"].endswith("Z") for event in events)
    assert events[0]["content"] == {"prompt": "[REDACTED]", "model": "test-model"}
    assert events[1]["content"] == "Bearer [REDACTED]"
    assert events[1]["level"] == "DEBUG"
    assert stat.S_IMODE(trace_path.stat().st_mode) == 0o600


def test_execution_trace_writer_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.ndjson"
    target.write_text("preserve", encoding="utf-8")
    trace_path = tmp_path / "trace.ndjson"
    trace_path.symlink_to(target)

    with pytest.raises(OSError):
        ExecutionTraceWriter(trace_path)
    assert target.read_text(encoding="utf-8") == "preserve"
