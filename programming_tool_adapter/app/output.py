from __future__ import annotations

import json
from typing import Any, Iterable


DISPLAY_BLOCK_SEPARATOR = "\n\x1e\n"


class StreamingSecretRedactor:
    """Redact exact sensitive values without leaking values split across chunks."""

    def __init__(self, sensitive_values: Iterable[str] = ()) -> None:
        self.sensitive_values = tuple(sorted({value for value in sensitive_values if value}, key=len, reverse=True))
        self.pending = ""

    def _consume(self, *, final: bool) -> str:
        if not self.sensitive_values:
            result, self.pending = self.pending, ""
            return result
        output: list[str] = []
        while self.pending:
            if not final and any(value.startswith(self.pending) for value in self.sensitive_values):
                break
            match = next((value for value in self.sensitive_values if self.pending.startswith(value)), None)
            if match:
                output.append("[REDACTED]")
                self.pending = self.pending[len(match):]
            else:
                output.append(self.pending[0])
                self.pending = self.pending[1:]
        return "".join(output)

    def feed(self, text: str) -> str:
        self.pending += text
        return self._consume(final=False)

    def finish(self) -> str:
        return self._consume(final=True)


class MarkdownCodeBlockFilter:
    """Remove fenced Markdown code, including fences split across stream chunks."""

    NORMAL = "normal"
    FENCE_HEADER = "fence_header"
    CODE = "code"
    FENCE_TAIL = "fence_tail"

    def __init__(self) -> None:
        self.state = self.NORMAL
        self.marker = ""
        self.pending = ""

    def feed(self, text: str) -> str:
        output: list[str] = []
        for char in text:
            if self.state == self.NORMAL:
                if char in {"`", "~"}:
                    if not self.pending or self.pending[0] == char:
                        self.pending += char
                        if len(self.pending) == 3:
                            self.marker = char
                            self.pending = ""
                            self.state = self.FENCE_HEADER
                        continue
                if self.pending:
                    output.append(self.pending)
                    self.pending = ""
                output.append(char)
                continue

            if self.state == self.FENCE_HEADER:
                if char == "\n":
                    self.state = self.CODE
                continue

            if self.state == self.CODE:
                if char == self.marker:
                    self.pending += char
                    if len(self.pending) == 3:
                        self.pending = ""
                        self.state = self.FENCE_TAIL
                    continue
                self.pending = ""
                continue

            if self.state == self.FENCE_TAIL:
                if char == "\n":
                    self.state = self.NORMAL
                    self.marker = ""
                continue
        return "".join(output)

    def finish(self) -> str:
        if self.state == self.NORMAL:
            result = self.pending
        else:
            result = ""
        self.pending = ""
        return result


class StructuredOutputParser:
    def __init__(self, tool_id: str, sensitive_values: Iterable[str] = ()) -> None:
        self.tool_id = tool_id
        self.filter = MarkdownCodeBlockFilter()
        self.redactor = StreamingSecretRedactor(sensitive_values)
        self.saw_display = False
        self.saw_stream_delta = False
        self.opencode_usage: dict[str, Any] = {}
        self.native_session_id = ""
        self.claude_stream_block_open = False
        self.opencode_text_part_id = ""
        self.opencode_next_text_starts_block = True

    def _capture_native_session_id(self, event: dict[str, Any]) -> None:
        candidate = ""
        if self.tool_id == "codex" and event.get("type") == "thread.started":
            candidate = str(event.get("thread_id") or "").strip()
        elif self.tool_id in {"claude_code", "codebuddy"}:
            candidate = str(event.get("session_id") or "").strip()
        elif self.tool_id == "opencode":
            for payload in (event, event.get("part"), event.get("message")):
                if not isinstance(payload, dict):
                    continue
                candidate = str(
                    payload.get("sessionID")
                    or payload.get("sessionId")
                    or payload.get("session_id")
                    or ""
                ).strip()
                if candidate:
                    break
        elif self.tool_id == "kimi_code":
            if event.get("role") == "meta" and event.get("type") == "session.resume_hint":
                candidate = str(event.get("session_id") or "").strip()
        if candidate and not self.native_session_id:
            self.native_session_id = candidate

    @classmethod
    def _sum_usage(cls, current: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
        """Accumulate OpenCode's per-step usage into run-level totals."""
        merged = dict(current)
        for key, value in delta.items():
            existing = merged.get(key)
            if isinstance(value, dict):
                merged[key] = cls._sum_usage(existing if isinstance(existing, dict) else {}, value)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                base = existing if isinstance(existing, (int, float)) and not isinstance(existing, bool) else 0
                merged[key] = base + value
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _text_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)

    def _codex_text(self, event: dict[str, Any]) -> tuple[str, bool]:
        if event.get("type") != "item.completed":
            return "", False
        item = event.get("item") or {}
        if item.get("type") != "agent_message":
            return "", False
        text = str(item.get("text") or "")
        return text, bool(text)

    def _claude_text(self, event: dict[str, Any]) -> tuple[str, bool]:
        event_type = event.get("type")
        if event_type == "stream_event":
            stream_event = event.get("event") or {}
            stream_type = stream_event.get("type")
            if stream_type == "message_start":
                self.claude_stream_block_open = False
                return "", False
            if stream_type == "content_block_start":
                content_block = stream_event.get("content_block") or {}
                if content_block.get("type") in {None, "text"}:
                    self.claude_stream_block_open = False
                return "", False
            if stream_type in {"content_block_stop", "message_stop"}:
                self.claude_stream_block_open = False
                return "", False
            delta = stream_event.get("delta") or {}
            if stream_type == "content_block_delta" and delta.get("type") == "text_delta":
                self.saw_stream_delta = True
                text = str(delta.get("text") or "")
                starts_block = bool(text) and not self.claude_stream_block_open
                if text:
                    self.claude_stream_block_open = True
                return text, starts_block
            return "", False
        if event_type == "assistant":
            if self.saw_stream_delta:
                return "", False
            message = event.get("message") or {}
            text = self._text_content(message.get("content"))
            return text, bool(text)
        if event_type == "result" and not self.saw_display:
            text = str(event.get("result") or "")
            return text, bool(text)
        return "", False

    def _opencode_text(self, event: dict[str, Any]) -> tuple[str, bool]:
        if event.get("type") not in {"text", "message", "assistant"}:
            return "", False
        part = event.get("part") or {}
        text = ""
        if isinstance(part, dict) and part.get("type") in {None, "text"}:
            candidate = part.get("text")
            if isinstance(candidate, str):
                text = candidate
        message = event.get("message") or {}
        if not text and isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                text = content
        if not text:
            candidate = event.get("text")
            text = candidate if isinstance(candidate, str) else ""
        if not text:
            return "", False

        part_id = ""
        for payload in (part, message, event):
            if not isinstance(payload, dict):
                continue
            part_id = str(
                payload.get("id")
                or payload.get("partID")
                or payload.get("partId")
                or ""
            ).strip()
            if part_id:
                break
        starts_block = self.opencode_next_text_starts_block or event.get("type") in {"message", "assistant"}
        if part_id:
            starts_block = starts_block or part_id != self.opencode_text_part_id
            self.opencode_text_part_id = part_id
        self.opencode_next_text_starts_block = False
        return text, starts_block

    @staticmethod
    def _kimi_text(event: dict[str, Any]) -> tuple[str, bool]:
        if event.get("role") != "assistant":
            return "", False
        content = event.get("content")
        if isinstance(content, str):
            return content, bool(content)
        return "", False

    def parse_line(self, line: str) -> list[dict[str, Any]]:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(event, dict):
            return []

        self._capture_native_session_id(event)

        usage = event.get("usage")
        if not isinstance(usage, dict):
            message = event.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
        if self.tool_id == "opencode" and event.get("type") == "step_finish":
            part = event.get("part")
            if isinstance(part, dict) and isinstance(part.get("tokens"), dict):
                usage = dict(part["tokens"])
                if part.get("cost") is not None:
                    usage["cost"] = part["cost"]
                self.opencode_usage = self._sum_usage(self.opencode_usage, usage)
                usage = dict(self.opencode_usage)
            self.opencode_next_text_starts_block = True

        if self.tool_id == "codex":
            text, starts_block = self._codex_text(event)
        elif self.tool_id in {"claude_code", "codebuddy"}:
            text, starts_block = self._claude_text(event)
        elif self.tool_id == "opencode":
            text, starts_block = self._opencode_text(event)
        elif self.tool_id == "kimi_code":
            text, starts_block = self._kimi_text(event)
        else:
            text, starts_block = "", False

        parsed: list[dict[str, Any]] = []
        if isinstance(usage, dict) and usage:
            parsed.append({"type": "usage", "usage": usage})
        if text:
            source = text
            if starts_block and self.saw_display:
                source = DISPLAY_BLOCK_SEPARATOR + text.lstrip("\r\n")
            display = self.redactor.feed(self.filter.feed(source))
            if display:
                self.saw_display = True
                parsed.append({"type": "display_delta", "content": display})
        return parsed

    def finish(self) -> list[dict[str, Any]]:
        trailing = self.redactor.feed(self.filter.finish()) + self.redactor.finish()
        return [{"type": "display_delta", "content": trailing}] if trailing else []
