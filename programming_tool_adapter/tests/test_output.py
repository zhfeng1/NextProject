import pytest

from programming_tool_adapter.app.output import MarkdownCodeBlockFilter, StreamingSecretRedactor, StructuredOutputParser


def test_code_fence_is_removed_across_chunks() -> None:
    output_filter = MarkdownCodeBlockFilter()
    visible = output_filter.feed("说明\n``")
    visible += output_filter.feed("`python\nprint('secret')\n```\n完成")
    visible += output_filter.finish()
    assert visible == "说明\n完成"


def test_codex_only_exposes_agent_message() -> None:
    parser = StructuredOutputParser("codex")
    assert parser.parse_line('{"type":"item.completed","item":{"type":"command_execution","text":"hidden"}}') == []
    assert parser.parse_line('{"type":"item.completed","item":{"type":"agent_message","text":"完成"}}') == [
        {"type": "display_delta", "content": "完成"}
    ]


def test_codex_agent_messages_keep_separate_display_blocks() -> None:
    parser = StructuredOutputParser("codex")

    first = parser.parse_line(
        '{"type":"item.completed","item":{"type":"agent_message","text":"第一步"}}'
    )
    second = parser.parse_line(
        '{"type":"item.completed","item":{"type":"agent_message","text":"第二步"}}'
    )

    assert first == [{"type": "display_delta", "content": "第一步"}]
    assert second == [{"type": "display_delta", "content": "\n\x1e\n第二步"}]


@pytest.mark.parametrize(
    ("tool_id", "event", "expected"),
    [
        ("codex", '{"type":"thread.started","thread_id":"codex-session"}', "codex-session"),
        ("claude_code", '{"type":"system","subtype":"init","session_id":"claude-session"}', "claude-session"),
        ("codebuddy", '{"type":"result","session_id":"codebuddy-session"}', "codebuddy-session"),
        ("opencode", '{"type":"text","sessionID":"opencode-session","part":{}}', "opencode-session"),
        (
            "kimi_code",
            '{"role":"meta","type":"session.resume_hint","session_id":"kimi-session"}',
            "kimi-session",
        ),
    ],
)
def test_parser_captures_native_session_id(tool_id: str, event: str, expected: str) -> None:
    parser = StructuredOutputParser(tool_id)
    parser.parse_line(event)
    assert parser.native_session_id == expected


def test_opencode_only_exposes_text_parts() -> None:
    parser = StructuredOutputParser("opencode")
    assert parser.parse_line('{"type":"tool_use","part":{"text":"hidden"}}') == []
    assert parser.parse_line('{"type":"text","part":{"type":"text","text":"done"}}') == [
        {"type": "display_delta", "content": "done"}
    ]


def test_kimi_only_exposes_assistant_content_and_keeps_blocks_separate() -> None:
    parser = StructuredOutputParser("kimi_code")

    assert parser.parse_line('{"role":"tool","tool_call_id":"call-1","content":"hidden"}') == []
    assert parser.parse_line('{"role":"meta","type":"turn.step.retrying","error_message":"hidden"}') == []
    assert parser.parse_line('{not-json') == []
    assert parser.parse_line('{"role":"assistant","content":"第一步"}') == [
        {"type": "display_delta", "content": "第一步"},
    ]
    assert parser.parse_line('{"role":"assistant","content":"第二步"}') == [
        {"type": "display_delta", "content": "\n\x1e\n第二步"},
    ]


def test_secret_is_redacted_across_chunks() -> None:
    redactor = StreamingSecretRedactor(["top-secret-key"])
    visible = redactor.feed("before top-sec")
    visible += redactor.feed("ret-key after")
    visible += redactor.finish()
    assert visible == "before [REDACTED] after"


def test_display_output_redacts_provider_key() -> None:
    parser = StructuredOutputParser("codex", ["top-secret-key"])
    events = parser.parse_line(
        '{"type":"item.completed","item":{"type":"agent_message","text":"key=top-secret-key"}}'
    )
    events += parser.finish()
    assert "".join(event["content"] for event in events) == "key=[REDACTED]"


def test_opencode_step_finish_emits_usage() -> None:
    parser = StructuredOutputParser("opencode")
    assert parser.parse_line(
        '{"type":"step_finish","part":{"type":"step-finish","tokens":{"input":12,"output":4},"cost":0.01}}'
    ) == [{"type": "usage", "usage": {"input": 12, "output": 4, "cost": 0.01}}]


def test_opencode_usage_accumulates_across_tool_steps() -> None:
    parser = StructuredOutputParser("opencode")

    first = parser.parse_line(
        '{"type":"step_finish","part":{"tokens":{"total":16,"input":12,"output":4,'
        '"cache":{"write":1,"read":2}},"cost":1}}'
    )
    second = parser.parse_line(
        '{"type":"step_finish","part":{"tokens":{"total":10,"input":7,"output":3,'
        '"cache":{"write":0,"read":5}},"cost":2}}'
    )

    assert first == [{
        "type": "usage",
        "usage": {
            "total": 16,
            "input": 12,
            "output": 4,
            "cache": {"write": 1, "read": 2},
            "cost": 1,
        },
    }]
    assert second == [{
        "type": "usage",
        "usage": {
            "total": 26,
            "input": 19,
            "output": 7,
            "cache": {"write": 1, "read": 7},
            "cost": 3,
        },
    }]
