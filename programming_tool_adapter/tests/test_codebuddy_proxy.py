from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from programming_tool_adapter.app.codebuddy_proxy import (
    CodeBuddyProxyConfig,
    chat_request_to_messages,
    chat_request_to_responses,
    create_codebuddy_proxy_app,
)


def _chat_request(*, stream: bool = False) -> dict[str, Any]:
    return {
        "model": "codebuddy-default",
        "messages": [
            {"role": "system", "content": "Work carefully."},
            {"role": "user", "content": "Inspect the repository."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "project docs"},
        ],
        "tools": [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }],
        "tool_choice": {"type": "function", "function": {"name": "read_file"}},
        "max_completion_tokens": 123,
        "stream": stream,
    }


def _config(api_format: str) -> CodeBuddyProxyConfig:
    return CodeBuddyProxyConfig(
        api_format=api_format,  # type: ignore[arg-type]
        base_url="https://provider.example/v1",
        api_key="provider-secret",
        model="provider-model",
        inbound_token="one-time-local-token",
    )


async def _proxy_client(
    api_format: str,
    handler,
) -> httpx.AsyncClient:
    app = create_codebuddy_proxy_app(
        _config(api_format),
        transport=httpx.MockTransport(handler),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://proxy")


def _sse_payloads(text: str) -> list[dict[str, Any] | str]:
    payloads: list[dict[str, Any] | str] = []
    for block in text.split("\n\n"):
        data = "\n".join(
            line[5:].lstrip()
            for line in block.splitlines()
            if line.startswith("data:")
        )
        if not data:
            continue
        payloads.append(data if data == "[DONE]" else json.loads(data))
    return payloads


def test_chat_request_is_converted_to_responses_with_tools() -> None:
    converted = chat_request_to_responses(_chat_request(), "provider-model")

    assert converted["model"] == "provider-model"
    assert converted["instructions"] == "Work carefully."
    assert converted["max_output_tokens"] == 123
    assert converted["tool_choice"] == {"type": "function", "name": "read_file"}
    assert converted["tools"][0] == {
        "type": "function",
        "name": "read_file",
        "description": "Read a file",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }
    assert {"type": "function_call", "call_id": "call_1", "name": "read_file", "arguments": '{"path":"README.md"}'} in converted["input"]
    assert {"type": "function_call_output", "call_id": "call_1", "output": "project docs"} in converted["input"]


def test_chat_request_is_converted_to_messages_with_tools() -> None:
    converted = chat_request_to_messages(_chat_request(), "provider-model")

    assert converted["model"] == "provider-model"
    assert converted["system"] == "Work carefully."
    assert converted["max_tokens"] == 123
    assert converted["tool_choice"] == {"type": "tool", "name": "read_file"}
    assistant = converted["messages"][1]
    assert assistant == {
        "role": "assistant",
        "content": [{
            "type": "tool_use",
            "id": "call_1",
            "name": "read_file",
            "input": {"path": "README.md"},
        }],
    }
    assert converted["messages"][2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "project docs"}],
    }


@pytest.mark.asyncio
async def test_responses_non_stream_proxy_converts_response_and_keeps_key_in_header_only() -> None:
    captured: dict[str, Any] = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "resp_1",
            "object": "response",
            "created_at": 42,
            "model": "provider-model",
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "Done."}]},
                {
                    "type": "function_call",
                    "call_id": "call_2",
                    "name": "write_file",
                    "arguments": '{"path":"x"}',
                },
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                "total_tokens": 14,
                "output_tokens_details": {"reasoning_tokens": 2},
            },
        })

    client = await _proxy_client("responses", upstream)
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer one-time-local-token"},
            json=_chat_request(),
        )

    assert response.status_code == 200
    assert captured["url"] == "https://provider.example/v1/responses"
    assert captured["headers"]["authorization"] == "Bearer provider-secret"
    assert "provider-secret" not in json.dumps(captured["body"])
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"] == {
        "role": "assistant",
        "content": "Done.",
        "tool_calls": [{
            "id": "call_2",
            "type": "function",
            "function": {"name": "write_file", "arguments": '{"path":"x"}'},
        }],
    }
    assert payload["choices"][0]["finish_reason"] == "tool_calls"
    assert payload["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
        "completion_tokens_details": {"reasoning_tokens": 2},
    }


@pytest.mark.asyncio
async def test_messages_non_stream_proxy_converts_request_response_tools_and_usage() -> None:
    captured: dict[str, Any] = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "msg_1",
            "type": "message",
            "model": "provider-model",
            "content": [
                {"type": "text", "text": "Need a tool."},
                {"type": "tool_use", "id": "tool_9", "name": "shell", "input": {"cmd": "pwd"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 8, "output_tokens": 3, "cache_read_input_tokens": 2},
        })

    client = await _proxy_client("messages", upstream)
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"x-api-key": "one-time-local-token"},
            json=_chat_request(),
        )

    assert response.status_code == 200
    assert captured["url"] == "https://provider.example/v1/messages"
    assert captured["headers"]["x-api-key"] == "provider-secret"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["model"] == "provider-model"
    payload = response.json()
    assert payload["choices"][0]["finish_reason"] == "tool_calls"
    assert payload["choices"][0]["message"]["tool_calls"][0]["function"] == {
        "name": "shell",
        "arguments": '{"cmd":"pwd"}',
    }
    assert payload["usage"] == {
        "prompt_tokens": 8,
        "completion_tokens": 3,
        "total_tokens": 11,
        "prompt_tokens_details": {"cached_tokens": 2},
    }


@pytest.mark.asyncio
async def test_responses_stream_is_converted_to_chat_sse_with_tool_calls_and_usage() -> None:
    events = [
        ("response.created", {
            "type": "response.created",
            "response": {"id": "resp_stream", "model": "provider-model", "created_at": 99},
        }),
        ("response.output_text.delta", {"type": "response.output_text.delta", "delta": "Working. "}),
        ("response.output_item.added", {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "shell", "arguments": ""},
        }),
        ("response.function_call_arguments.delta", {
            "type": "response.function_call_arguments.delta",
            "output_index": 1,
            "item_id": "fc_1",
            "delta": '{"cmd":"pwd"}',
        }),
        ("response.completed", {
            "type": "response.completed",
            "response": {
                "id": "resp_stream",
                "model": "provider-model",
                "status": "completed",
                "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
            },
        }),
    ]
    raw = "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)

    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=raw.encode())

    client = await _proxy_client("responses", upstream)
    async with client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            headers={"Authorization": "Bearer one-time-local-token"},
            json=_chat_request(stream=True),
        ) as response:
            body = (await response.aread()).decode()

    payloads = _sse_payloads(body)
    assert payloads[-1] == "[DONE]"
    chunks = [item for item in payloads if isinstance(item, dict)]
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert any(chunk["choices"][0]["delta"].get("content") == "Working. " for chunk in chunks)
    tool_deltas = [
        chunk["choices"][0]["delta"]["tool_calls"][0]
        for chunk in chunks
        if chunk["choices"][0]["delta"].get("tool_calls")
    ]
    assert tool_deltas[0]["id"] == "call_1"
    assert tool_deltas[0]["function"]["name"] == "shell"
    assert tool_deltas[1]["function"]["arguments"] == '{"cmd":"pwd"}'
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1]["usage"] == {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}


@pytest.mark.asyncio
async def test_messages_stream_is_converted_to_chat_sse_with_tool_calls_and_usage() -> None:
    events = [
        ("message_start", {
            "type": "message_start",
            "message": {"id": "msg_stream", "model": "provider-model", "usage": {"input_tokens": 6}},
        }),
        ("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": "Checking. "},
        }),
        ("content_block_start", {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "tool_1", "name": "read_file", "input": {}},
        }),
        ("content_block_delta", {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":"README.md"}'},
        }),
        ("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 4},
        }),
        ("message_stop", {"type": "message_stop"}),
    ]
    raw = "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)

    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=raw.encode())

    client = await _proxy_client("messages", upstream)
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer one-time-local-token"},
            json=_chat_request(stream=True),
        )

    payloads = _sse_payloads(response.text)
    assert payloads[-1] == "[DONE]"
    chunks = [item for item in payloads if isinstance(item, dict)]
    assert any(chunk["choices"][0]["delta"].get("content") == "Checking. " for chunk in chunks)
    tool_deltas = [
        chunk["choices"][0]["delta"]["tool_calls"][0]
        for chunk in chunks
        if chunk["choices"][0]["delta"].get("tool_calls")
    ]
    assert tool_deltas[0]["id"] == "tool_1"
    assert tool_deltas[0]["function"]["name"] == "read_file"
    assert tool_deltas[1]["function"]["arguments"] == '{"path":"README.md"}'
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1]["usage"] == {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10}


@pytest.mark.asyncio
async def test_chat_completions_is_forwarded_without_exposing_provider_key_in_body() -> None:
    captured: dict[str, Any] = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "chat_1",
            "object": "chat.completion",
            "model": "provider-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        })

    client = await _proxy_client("chat_completions", upstream)
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer one-time-local-token"},
            json=_chat_request(),
        )

    assert response.status_code == 200
    assert captured["url"] == "https://provider.example/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer provider-secret"
    assert captured["body"]["model"] == "provider-model"
    assert "provider-secret" not in json.dumps(captured["body"])
    assert response.json()["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
async def test_proxy_rejects_wrong_local_token_without_calling_upstream() -> None:
    called = False

    async def upstream(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    client = await _proxy_client("responses", upstream)
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer wrong-token"},
            json=_chat_request(),
        )

    assert response.status_code == 401
    assert called is False
    assert "provider-secret" not in response.text
    assert "one-time-local-token" not in response.text


@pytest.mark.asyncio
async def test_upstream_error_redacts_provider_and_local_tokens() -> None:
    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={
            "error": {"message": "bad provider-secret and one-time-local-token"},
        })

    client = await _proxy_client("messages", upstream)
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer one-time-local-token"},
            json=_chat_request(),
        )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "bad [REDACTED] and [REDACTED]"
    assert "provider-secret" not in response.text
    assert "one-time-local-token" not in response.text
