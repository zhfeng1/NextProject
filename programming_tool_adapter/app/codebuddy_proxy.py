from __future__ import annotations

import hmac
import json
import socket
import time
import uuid
from asyncio import create_task, sleep, wait_for
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Iterator, Mapping

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .models import ApiFormat


_ENDPOINTS: dict[ApiFormat, str] = {
    "responses": "responses",
    "messages": "messages",
    "chat_completions": "chat/completions",
}


@dataclass(frozen=True, slots=True)
class ProviderProxyConfig:
    """Configuration for one short-lived programming-tool Provider proxy.

    The Provider API key deliberately has ``repr=False`` so diagnostics cannot
    accidentally include it. ``inbound_token`` should be a random per-run
        value passed to the CLI instead of the real Provider key.
    """

    api_format: ApiFormat
    base_url: str
    api_key: str = field(repr=False)
    model: str
    inbound_token: str = field(default="", repr=False)
    timeout_seconds: float = 1800.0
    anthropic_version: str = "2023-06-01"

    def __post_init__(self) -> None:
        if self.api_format not in _ENDPOINTS:
            raise ValueError(f"unsupported Provider proxy format: {self.api_format}")
        if not self.base_url.strip():
            raise ValueError("Provider proxy base_url is required")
        if not self.api_key:
            raise ValueError("Provider proxy api_key is required")
        if not self.model.strip():
            raise ValueError("Provider proxy model is required")
        if self.timeout_seconds <= 0:
            raise ValueError("Provider proxy timeout_seconds must be positive")

    @property
    def upstream_url(self) -> str:
        """Append the protocol endpoint to the configured Provider base URL.

        Project Providers store the API root (normally ending in ``/v1``),
        matching the model-validation API in the main service.
        """

        base_url = self.base_url.strip().rstrip("/")
        endpoint = _ENDPOINTS[self.api_format]
        if base_url.endswith(f"/{endpoint}"):
            return base_url
        return f"{base_url}/{endpoint}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, Mapping) and part.get("type") in {"text", "input_text", "output_text"}:
            parts.append(str(part.get("text") or ""))
    return "".join(parts)


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    if isinstance(value, Mapping):
        return dict(value)
    return {"value": value}


def _function_arguments(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    return _json_dumps(raw or {})


def _chat_tools_to_responses(tools: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, Mapping) or tool.get("type") != "function":
            continue
        function = tool.get("function")
        if not isinstance(function, Mapping) or not function.get("name"):
            continue
        converted: dict[str, Any] = {
            "type": "function",
            "name": str(function["name"]),
            "parameters": dict(function.get("parameters") or {}),
        }
        if function.get("description") is not None:
            converted["description"] = str(function["description"])
        if function.get("strict") is not None:
            converted["strict"] = bool(function["strict"])
        result.append(converted)
    return result


def _responses_tool_choice(choice: Any) -> Any:
    if not isinstance(choice, Mapping):
        return choice
    function = choice.get("function")
    if choice.get("type") == "function" and isinstance(function, Mapping) and function.get("name"):
        return {"type": "function", "name": str(function["name"])}
    return choice


def _responses_message_content(role: str, content: Any) -> Any:
    if not isinstance(content, list):
        return content
    converted: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, Mapping):
            continue
        part_type = str(part.get("type") or "")
        if part_type == "text":
            converted.append({
                "type": "output_text" if role == "assistant" else "input_text",
                "text": str(part.get("text") or ""),
            })
        elif part_type == "image_url" and role == "user":
            image = part.get("image_url")
            image_url = image.get("url") if isinstance(image, Mapping) else image
            if image_url:
                converted.append({"type": "input_image", "image_url": str(image_url)})
    return converted or _text_content(content)


def chat_request_to_responses(payload: Mapping[str, Any], model: str) -> dict[str, Any]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in payload.get("messages") if isinstance(payload.get("messages"), list) else []:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "user")
        if role in {"system", "developer"}:
            text = _text_content(message.get("content"))
            if text:
                instructions.append(text)
            continue
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            if call_id:
                input_items.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": _text_content(message.get("content")),
                })
            continue
        content = message.get("content")
        if content not in (None, "", []):
            input_items.append({
                "role": "assistant" if role == "assistant" else "user",
                "content": _responses_message_content(role, content),
            })
        if role == "assistant":
            for tool_call in message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []:
                if not isinstance(tool_call, Mapping):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, Mapping) or not function.get("name"):
                    continue
                input_items.append({
                    "type": "function_call",
                    "call_id": str(tool_call.get("id") or f"call_{uuid.uuid4().hex}"),
                    "name": str(function["name"]),
                    "arguments": _function_arguments(function.get("arguments")),
                })

    converted: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "stream": bool(payload.get("stream")),
    }
    if instructions:
        converted["instructions"] = "\n\n".join(instructions)
    tools = _chat_tools_to_responses(payload.get("tools"))
    if tools:
        converted["tools"] = tools
    if payload.get("tool_choice") is not None:
        converted["tool_choice"] = _responses_tool_choice(payload["tool_choice"])
    max_tokens = payload.get("max_completion_tokens", payload.get("max_tokens"))
    if max_tokens is not None:
        converted["max_output_tokens"] = max_tokens
    for name in ("temperature", "top_p", "parallel_tool_calls", "metadata", "store"):
        if payload.get(name) is not None:
            converted[name] = payload[name]
    if payload.get("reasoning_effort") is not None:
        converted["reasoning"] = {"effort": payload["reasoning_effort"]}
    return converted


def _chat_tools_to_messages(tools: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, Mapping) or tool.get("type") != "function":
            continue
        function = tool.get("function")
        if not isinstance(function, Mapping) or not function.get("name"):
            continue
        converted: dict[str, Any] = {
            "name": str(function["name"]),
            "input_schema": dict(function.get("parameters") or {"type": "object", "properties": {}}),
        }
        if function.get("description") is not None:
            converted["description"] = str(function["description"])
        result.append(converted)
    return result


def _anthropic_text_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    result: list[dict[str, Any]] = []
    for part in content if isinstance(content, list) else []:
        if isinstance(part, str):
            result.append({"type": "text", "text": part})
        elif isinstance(part, Mapping) and part.get("type") == "text":
            result.append({"type": "text", "text": str(part.get("text") or "")})
        elif isinstance(part, Mapping) and part.get("type") == "image_url":
            image = part.get("image_url")
            image_url = image.get("url") if isinstance(image, Mapping) else image
            if image_url:
                result.append({"type": "image", "source": {"type": "url", "url": str(image_url)}})
    return result


def _append_anthropic_message(messages: list[dict[str, Any]], role: str, blocks: list[dict[str, Any]]) -> None:
    if not blocks:
        return
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].extend(blocks)
    else:
        messages.append({"role": role, "content": blocks})


def _anthropic_tool_choice(choice: Any) -> dict[str, Any] | None:
    if choice == "auto":
        return {"type": "auto"}
    if choice == "required":
        return {"type": "any"}
    if not isinstance(choice, Mapping):
        return None
    function = choice.get("function")
    if choice.get("type") == "function" and isinstance(function, Mapping) and function.get("name"):
        return {"type": "tool", "name": str(function["name"])}
    return None


def chat_request_to_messages(payload: Mapping[str, Any], model: str) -> dict[str, Any]:
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []
    for message in payload.get("messages") if isinstance(payload.get("messages"), list) else []:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "user")
        if role in {"system", "developer"}:
            text = _text_content(message.get("content"))
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            if call_id:
                _append_anthropic_message(messages, "user", [{
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": _text_content(message.get("content")),
                }])
            continue
        anthropic_role = "assistant" if role == "assistant" else "user"
        blocks = _anthropic_text_blocks(message.get("content"))
        if anthropic_role == "assistant":
            for tool_call in message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []:
                if not isinstance(tool_call, Mapping):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, Mapping) or not function.get("name"):
                    continue
                blocks.append({
                    "type": "tool_use",
                    "id": str(tool_call.get("id") or f"call_{uuid.uuid4().hex}"),
                    "name": str(function["name"]),
                    "input": _json_object(function.get("arguments")),
                })
        _append_anthropic_message(messages, anthropic_role, blocks)

    max_tokens = payload.get("max_completion_tokens", payload.get("max_tokens", 8192))
    converted: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": bool(payload.get("stream")),
    }
    if system_parts:
        converted["system"] = "\n\n".join(system_parts)
    tools = _chat_tools_to_messages(payload.get("tools"))
    if payload.get("tool_choice") == "none":
        tools = []
    if tools:
        converted["tools"] = tools
    tool_choice = _anthropic_tool_choice(payload.get("tool_choice"))
    if tool_choice and tools:
        converted["tool_choice"] = tool_choice
    if payload.get("stop") is not None:
        stop = payload["stop"]
        converted["stop_sequences"] = [stop] if isinstance(stop, str) else stop
    for name in ("temperature", "top_p", "top_k", "metadata"):
        if payload.get(name) is not None:
            converted[name] = payload[name]
    return converted


def _responses_usage(usage: Any) -> dict[str, Any] | None:
    if not isinstance(usage, Mapping):
        return None
    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)
    converted: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
    }
    output_details = usage.get("output_tokens_details")
    if isinstance(output_details, Mapping) and output_details.get("reasoning_tokens") is not None:
        converted["completion_tokens_details"] = {
            "reasoning_tokens": int(output_details["reasoning_tokens"] or 0),
        }
    input_details = usage.get("input_tokens_details")
    if isinstance(input_details, Mapping) and input_details.get("cached_tokens") is not None:
        converted["prompt_tokens_details"] = {
            "cached_tokens": int(input_details["cached_tokens"] or 0),
        }
    return converted


def _messages_usage(usage: Any) -> dict[str, Any] | None:
    if not isinstance(usage, Mapping):
        return None
    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)
    converted: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    cached_tokens = int(usage.get("cache_read_input_tokens") or 0)
    if cached_tokens:
        converted["prompt_tokens_details"] = {"cached_tokens": cached_tokens}
    return converted


def _responses_finish_reason(response: Mapping[str, Any], has_tool_calls: bool) -> str:
    if response.get("status") == "incomplete":
        return "length"
    return "tool_calls" if has_tool_calls else "stop"


def _messages_finish_reason(reason: Any, has_tool_calls: bool = False) -> str:
    return {
        "max_tokens": "length",
        "tool_use": "tool_calls",
        "end_turn": "stop",
        "stop_sequence": "stop",
        "pause_turn": "stop",
        "refusal": "content_filter",
    }.get(str(reason or ""), "tool_calls" if has_tool_calls else "stop")


def responses_response_to_chat(payload: Mapping[str, Any], requested_model: str) -> dict[str, Any]:
    content_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for item in payload.get("output") if isinstance(payload.get("output"), list) else []:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "message":
            for part in item.get("content") if isinstance(item.get("content"), list) else []:
                if isinstance(part, Mapping) and part.get("type") in {"output_text", "text", "refusal"}:
                    content_parts.append(str(part.get("text") or part.get("refusal") or ""))
        elif item.get("type") == "function_call":
            tool_calls.append({
                "id": str(item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex}"),
                "type": "function",
                "function": {
                    "name": str(item.get("name") or ""),
                    "arguments": _function_arguments(item.get("arguments")),
                },
            })
    if not content_parts and payload.get("output_text"):
        content_parts.append(str(payload["output_text"]))
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content_parts) if content_parts else None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    result: dict[str, Any] = {
        "id": str(payload.get("id") or f"chatcmpl-proxy-{uuid.uuid4().hex}"),
        "object": "chat.completion",
        "created": int(payload.get("created_at") or time.time()),
        "model": str(payload.get("model") or requested_model),
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": _responses_finish_reason(payload, bool(tool_calls)),
        }],
    }
    usage = _responses_usage(payload.get("usage"))
    if usage:
        result["usage"] = usage
    return result


def messages_response_to_chat(payload: Mapping[str, Any], requested_model: str) -> dict[str, Any]:
    content_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in payload.get("content") if isinstance(payload.get("content"), list) else []:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "text":
            content_parts.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": str(block.get("id") or f"call_{uuid.uuid4().hex}"),
                "type": "function",
                "function": {
                    "name": str(block.get("name") or ""),
                    "arguments": _function_arguments(block.get("input")),
                },
            })
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content_parts) if content_parts else None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    result: dict[str, Any] = {
        "id": str(payload.get("id") or f"chatcmpl-proxy-{uuid.uuid4().hex}"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": str(payload.get("model") or requested_model),
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": _messages_finish_reason(payload.get("stop_reason"), bool(tool_calls)),
        }],
    }
    usage = _messages_usage(payload.get("usage"))
    if usage:
        result["usage"] = usage
    return result


async def _sse_events(response: httpx.Response) -> AsyncIterator[tuple[str, str]]:
    event_type = ""
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if event_type or data_lines:
                yield event_type, "\n".join(data_lines)
            event_type = ""
            data_lines = []
        elif line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if event_type or data_lines:
        yield event_type, "\n".join(data_lines)


def _sse_data(payload: Mapping[str, Any] | str) -> bytes:
    data = payload if isinstance(payload, str) else _json_dumps(payload)
    return f"data: {data}\n\n".encode("utf-8")


@dataclass(slots=True)
class _ChatStreamState:
    requested_model: str
    response_id: str = field(default_factory=lambda: f"chatcmpl-proxy-{uuid.uuid4().hex}")
    model: str = ""
    created: int = field(default_factory=lambda: int(time.time()))
    role_emitted: bool = False
    done: bool = False
    tool_indices: dict[str, int] = field(default_factory=dict)
    next_tool_index: int = 0
    usage: dict[str, Any] | None = None

    def chunk(
        self,
        *,
        delta: Mapping[str, Any] | None = None,
        finish_reason: str | None = None,
        usage: Mapping[str, Any] | None = None,
    ) -> bytes:
        result: dict[str, Any] = {
            "id": self.response_id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model or self.requested_model,
            "choices": [{
                "index": 0,
                "delta": dict(delta or {}),
                "finish_reason": finish_reason,
            }],
        }
        if usage:
            result["usage"] = dict(usage)
        return _sse_data(result)

    def role_chunk(self) -> bytes | None:
        if self.role_emitted:
            return None
        self.role_emitted = True
        return self.chunk(delta={"role": "assistant", "content": ""})

    def tool_index(self, *keys: Any) -> int:
        normalized = next((str(key) for key in keys if key not in (None, "")), "")
        if normalized and normalized in self.tool_indices:
            return self.tool_indices[normalized]
        index = self.next_tool_index
        self.next_tool_index += 1
        if normalized:
            self.tool_indices[normalized] = index
        return index


async def responses_stream_to_chat(
    response: httpx.Response,
    requested_model: str,
) -> AsyncIterator[bytes]:
    state = _ChatStreamState(requested_model=requested_model)
    async for event_name, raw_data in _sse_events(response):
        if raw_data == "[DONE]":
            break
        try:
            event = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("type") or event_name)
        response_payload = event.get("response")
        if event_type in {"response.created", "response.in_progress"} and isinstance(response_payload, Mapping):
            state.response_id = str(response_payload.get("id") or state.response_id)
            state.model = str(response_payload.get("model") or state.model)
            state.created = int(response_payload.get("created_at") or state.created)
            role_chunk = state.role_chunk()
            if role_chunk:
                yield role_chunk
        elif event_type == "response.output_text.delta":
            role_chunk = state.role_chunk()
            if role_chunk:
                yield role_chunk
            yield state.chunk(delta={"content": str(event.get("delta") or "")})
        elif event_type == "response.refusal.delta":
            role_chunk = state.role_chunk()
            if role_chunk:
                yield role_chunk
            yield state.chunk(delta={"content": str(event.get("delta") or "")})
        elif event_type == "response.output_item.added":
            item = event.get("item")
            if not isinstance(item, Mapping) or item.get("type") != "function_call":
                continue
            role_chunk = state.role_chunk()
            if role_chunk:
                yield role_chunk
            index = state.tool_index(event.get("output_index"), item.get("id"), item.get("call_id"))
            for key in (item.get("id"), item.get("call_id"), event.get("output_index")):
                if key not in (None, ""):
                    state.tool_indices[str(key)] = index
            yield state.chunk(delta={"tool_calls": [{
                "index": index,
                "id": str(item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex}"),
                "type": "function",
                "function": {
                    "name": str(item.get("name") or ""),
                    "arguments": str(item.get("arguments") or ""),
                },
            }]})
        elif event_type == "response.function_call_arguments.delta":
            role_chunk = state.role_chunk()
            if role_chunk:
                yield role_chunk
            index = state.tool_index(event.get("item_id"), event.get("output_index"))
            yield state.chunk(delta={"tool_calls": [{
                "index": index,
                "function": {"arguments": str(event.get("delta") or "")},
            }]})
        elif event_type in {"response.completed", "response.incomplete"}:
            completed = response_payload if isinstance(response_payload, Mapping) else event
            state.response_id = str(completed.get("id") or state.response_id)
            state.model = str(completed.get("model") or state.model)
            state.usage = _responses_usage(completed.get("usage"))
            role_chunk = state.role_chunk()
            if role_chunk:
                yield role_chunk
            finish_reason = _responses_finish_reason(completed, state.next_tool_index > 0)
            yield state.chunk(delta={}, finish_reason=finish_reason, usage=state.usage)
            state.done = True
            yield _sse_data("[DONE]")
            return
        elif event_type in {"response.failed", "error"}:
            error = event.get("error")
            message = error.get("message") if isinstance(error, Mapping) else "upstream response failed"
            yield _sse_data({"error": {"message": str(message), "type": "upstream_error"}})
            state.done = True
            yield _sse_data("[DONE]")
            return
    if not state.done:
        role_chunk = state.role_chunk()
        if role_chunk:
            yield role_chunk
        yield state.chunk(delta={}, finish_reason="stop", usage=state.usage)
        yield _sse_data("[DONE]")


async def messages_stream_to_chat(
    response: httpx.Response,
    requested_model: str,
) -> AsyncIterator[bytes]:
    state = _ChatStreamState(requested_model=requested_model)
    input_usage: dict[str, Any] = {}
    tool_blocks: dict[int, int] = {}
    async for event_name, raw_data in _sse_events(response):
        if raw_data == "[DONE]":
            break
        try:
            event = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("type") or event_name)
        if event_type == "message_start":
            message = event.get("message")
            if isinstance(message, Mapping):
                state.response_id = str(message.get("id") or state.response_id)
                state.model = str(message.get("model") or state.model)
                if isinstance(message.get("usage"), Mapping):
                    input_usage.update(message["usage"])
            role_chunk = state.role_chunk()
            if role_chunk:
                yield role_chunk
        elif event_type == "content_block_start":
            block = event.get("content_block")
            if not isinstance(block, Mapping):
                continue
            role_chunk = state.role_chunk()
            if role_chunk:
                yield role_chunk
            if block.get("type") == "text" and block.get("text"):
                yield state.chunk(delta={"content": str(block["text"])})
            elif block.get("type") == "tool_use":
                block_index = int(event.get("index") or 0)
                tool_index = state.tool_index(block.get("id"), block_index)
                tool_blocks[block_index] = tool_index
                yield state.chunk(delta={"tool_calls": [{
                    "index": tool_index,
                    "id": str(block.get("id") or f"call_{uuid.uuid4().hex}"),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name") or ""),
                        "arguments": _function_arguments(block.get("input")) if block.get("input") else "",
                    },
                }]})
        elif event_type == "content_block_delta":
            delta = event.get("delta")
            if not isinstance(delta, Mapping):
                continue
            role_chunk = state.role_chunk()
            if role_chunk:
                yield role_chunk
            if delta.get("type") == "text_delta":
                yield state.chunk(delta={"content": str(delta.get("text") or "")})
            elif delta.get("type") == "input_json_delta":
                block_index = int(event.get("index") or 0)
                tool_index = tool_blocks.get(block_index)
                if tool_index is None:
                    tool_index = state.tool_index(block_index)
                tool_blocks[block_index] = tool_index
                yield state.chunk(delta={"tool_calls": [{
                    "index": tool_index,
                    "function": {"arguments": str(delta.get("partial_json") or "")},
                }]})
        elif event_type == "message_delta":
            delta = event.get("delta")
            stop_reason = delta.get("stop_reason") if isinstance(delta, Mapping) else None
            usage = dict(input_usage)
            if isinstance(event.get("usage"), Mapping):
                usage.update(event["usage"])
            state.usage = _messages_usage(usage)
            role_chunk = state.role_chunk()
            if role_chunk:
                yield role_chunk
            yield state.chunk(
                delta={},
                finish_reason=_messages_finish_reason(stop_reason, state.next_tool_index > 0),
                usage=state.usage,
            )
            state.done = True
        elif event_type == "message_stop":
            if not state.done:
                role_chunk = state.role_chunk()
                if role_chunk:
                    yield role_chunk
                yield state.chunk(
                    delta={},
                    finish_reason="tool_calls" if state.next_tool_index else "stop",
                    usage=state.usage,
                )
            yield _sse_data("[DONE]")
            return
        elif event_type == "error":
            error = event.get("error")
            message = error.get("message") if isinstance(error, Mapping) else "upstream response failed"
            yield _sse_data({"error": {"message": str(message), "type": "upstream_error"}})
            state.done = True
            yield _sse_data("[DONE]")
            return
    if not state.done:
        role_chunk = state.role_chunk()
        if role_chunk:
            yield role_chunk
        yield state.chunk(
            delta={},
            finish_reason="tool_calls" if state.next_tool_index else "stop",
            usage=state.usage,
        )
    yield _sse_data("[DONE]")


def _redact(value: str, secrets: Iterable[str]) -> str:
    result = value
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result


def _upstream_error_message(raw_body: bytes, secrets: Iterable[str]) -> str:
    text = raw_body.decode("utf-8", errors="replace")[:4000]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _redact(text[:1000] or "upstream request failed", secrets)
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            text = str(error.get("message") or error.get("detail") or "upstream request failed")
        elif error:
            text = str(error)
        elif payload.get("detail"):
            text = str(payload["detail"])
    return _redact(text[:1000], secrets)


class ProviderProtocolProxy:
    """ASGI proxy that presents Chat Completions to a programming CLI.

    A proxy instance is intentionally scoped to a single adapter run. It never
    logs request bodies, headers, upstream URLs, or exception details.
    """

    def __init__(
        self,
        config: ProviderProxyConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.app = FastAPI(title="Programming Tool Provider Proxy", docs_url=None, redoc_url=None)
        self.app.add_api_route("/health", self.health, methods=["GET"])
        self.app.add_api_route("/v1/chat/completions", self.chat_completions, methods=["POST"])
        self.app.add_api_route("/chat/completions", self.chat_completions, methods=["POST"])

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "format": self.config.api_format}

    def _authorize(self, request: Request) -> None:
        expected = self.config.inbound_token
        if not expected:
            return
        authorization = request.headers.get("authorization", "")
        supplied = authorization[7:] if authorization.lower().startswith("bearer ") else ""
        supplied = supplied or request.headers.get("x-api-key", "")
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="invalid proxy token")

    def _headers(self) -> dict[str, str]:
        if self.config.api_format == "messages":
            return {
                "x-api-key": self.config.api_key,
                "anthropic-version": self.config.anthropic_version,
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
            }
        return {
            "authorization": f"Bearer {self.config.api_key}",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }

    def _payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self.config.api_format == "responses":
            return chat_request_to_responses(payload, self.config.model)
        if self.config.api_format == "messages":
            return chat_request_to_messages(payload, self.config.model)
        converted = dict(payload)
        converted["model"] = self.config.model
        return converted

    async def _error_response(self, response: httpx.Response, client: httpx.AsyncClient) -> JSONResponse:
        try:
            raw_body = await response.aread()
        finally:
            await response.aclose()
            await client.aclose()
        message = _upstream_error_message(
            raw_body,
            (self.config.api_key, self.config.inbound_token),
        )
        return JSONResponse(
            status_code=response.status_code,
            content={"error": {"message": message, "type": "upstream_error", "code": response.status_code}},
        )

    async def chat_completions(self, request: Request):
        self._authorize(request)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="request body must be valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail="request body must be a JSON object")
        upstream_payload = self._payload(payload)
        timeout = httpx.Timeout(
            connect=min(self.config.timeout_seconds, 30.0),
            read=self.config.timeout_seconds,
            write=min(self.config.timeout_seconds, 30.0),
            pool=min(self.config.timeout_seconds, 30.0),
        )
        client = httpx.AsyncClient(timeout=timeout, transport=self.transport, trust_env=False)
        try:
            upstream_request = client.build_request(
                "POST",
                self.config.upstream_url,
                headers=self._headers(),
                json=upstream_payload,
            )
            response = await client.send(upstream_request, stream=bool(payload.get("stream")))
        except httpx.HTTPError:
            await client.aclose()
            return JSONResponse(
                status_code=502,
                content={"error": {"message": "upstream request failed", "type": "upstream_error"}},
            )
        if response.status_code >= 400:
            return await self._error_response(response, client)

        if not payload.get("stream"):
            try:
                upstream_json = response.json()
                if not isinstance(upstream_json, Mapping):
                    raise ValueError("upstream response was not a JSON object")
                if self.config.api_format == "responses":
                    result = responses_response_to_chat(upstream_json, self.config.model)
                elif self.config.api_format == "messages":
                    result = messages_response_to_chat(upstream_json, self.config.model)
                else:
                    result = dict(upstream_json)
                return JSONResponse(content=result)
            except (json.JSONDecodeError, ValueError):
                return JSONResponse(
                    status_code=502,
                    content={"error": {"message": "invalid upstream response", "type": "upstream_error"}},
                )
            finally:
                await response.aclose()
                await client.aclose()

        async def stream_body() -> AsyncIterator[bytes]:
            try:
                if self.config.api_format == "responses":
                    async for chunk in responses_stream_to_chat(response, self.config.model):
                        yield chunk
                elif self.config.api_format == "messages":
                    async for chunk in messages_stream_to_chat(response, self.config.model):
                        yield chunk
                else:
                    async for chunk in response.aiter_raw():
                        yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_body(),
            status_code=response.status_code,
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )


def create_provider_proxy_app(
    config: ProviderProxyConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    return ProviderProtocolProxy(config, transport=transport).app


class _EmbeddedUvicornServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        # The adapter's outer Uvicorn process owns SIGINT/SIGTERM handling.
        yield


@dataclass(frozen=True, slots=True)
class RunningProviderProxy:
    base_url: str


@asynccontextmanager
async def serve_provider_proxy(
    config: ProviderProxyConfig,
) -> AsyncIterator[RunningProviderProxy]:
    """Run a per-task proxy on an ephemeral loopback-only port."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = int(listener.getsockname()[1])
    app = create_provider_proxy_app(config)
    server = _EmbeddedUvicornServer(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
        server_header=False,
    ))
    server_task = create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(200):
            if server.started:
                break
            if server_task.done():
                await server_task
                raise RuntimeError("Provider protocol proxy stopped during startup")
            await sleep(0.01)
        else:
            raise RuntimeError("Provider protocol proxy startup timed out")
        yield RunningProviderProxy(base_url=f"http://127.0.0.1:{port}")
    finally:
        server.should_exit = True
        try:
            await wait_for(server_task, timeout=5)
        except TimeoutError:
            server.force_exit = True
            server_task.cancel()
            with suppress(BaseException):
                await server_task
        listener.close()


# Backwards-compatible imports for existing integrations while the proxy is now
# shared by CodeBuddy and Kimi Code.
CodeBuddyProxyConfig = ProviderProxyConfig
CodeBuddyProtocolProxy = ProviderProtocolProxy
RunningCodeBuddyProxy = RunningProviderProxy
create_codebuddy_proxy_app = create_provider_proxy_app
serve_codebuddy_proxy = serve_provider_proxy
