from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_codex_user_output_only_uses_agent_message_and_filters_code_blocks() -> None:
    from backend.services.task_service import TaskService

    event = json.dumps({
        "type": "item.completed",
        "item": {
            "type": "agent_message",
            "text": "已完成页面优化。\n\n```python\nprint('hidden')\n```\n\n相关检查已通过。",
        },
    })

    output = TaskService._extract_codex_user_message(event)

    assert output == "已完成页面优化。\n\n相关检查已通过。"
    assert "print" not in output


@pytest.mark.parametrize("item_type", ["reasoning", "command_execution", "file_change", "mcp_tool_call"])
def test_codex_user_output_ignores_internal_item_types(item_type: str) -> None:
    from backend.services.task_service import TaskService

    event = json.dumps({
        "type": "item.completed",
        "item": {"type": item_type, "text": "不应展示", "command": "rm -rf example"},
    })

    assert TaskService._extract_codex_user_message(event) == ""


@pytest.mark.asyncio
async def test_provider_output_does_not_fall_back_to_raw_task_output(tmp_path, monkeypatch) -> None:
    from backend.services.task_service import TaskService

    service = TaskService()
    task = SimpleNamespace(
        id="task-with-legacy-raw-output",
        provider="codex",
        result_json={"output_tail": "```python\nprint('legacy raw')\n```"},
    )
    monkeypatch.setattr(service, "get_task", AsyncMock(return_value=task))
    monkeypatch.setattr(TaskService, "_task_artifacts_root", staticmethod(lambda: tmp_path))

    result = await service.get_task_provider_output(None, str(task.id), object())

    assert result["available"] is False
    assert result["content"] == ""


@pytest.mark.asyncio
async def test_provider_output_recovers_historical_codex_message_blocks(tmp_path, monkeypatch) -> None:
    from backend.services.task_service import TaskService

    service = TaskService()
    task = SimpleNamespace(id="historical-codex-output", provider="codex")
    task_dir = tmp_path / str(task.id)
    task_dir.mkdir()
    raw_path = task_dir / "codex-raw-output.log"
    raw_path.write_text("\n".join([
        json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "先检查现状。"},
        }, ensure_ascii=False),
        json.dumps({
            "type": "item.completed",
            "item": {"type": "command_execution", "text": "不应展示"},
        }, ensure_ascii=False),
        json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "检查完成。\n\n- 第一项\n- 第二项"},
        }, ensure_ascii=False),
    ]), encoding="utf-8")
    monkeypatch.setattr(service, "get_task", AsyncMock(return_value=task))
    monkeypatch.setattr(TaskService, "_task_artifacts_root", staticmethod(lambda: tmp_path))

    result = await service.get_task_provider_output(None, str(task.id), object())

    assert result["available"] is True
    assert result["content"] == "先检查现状。\n\x1e\n检查完成。\n\n- 第一项\n- 第二项"
    assert "不应展示" not in result["content"]


@pytest.mark.asyncio
async def test_adapter_cancellation_is_preserved_instead_of_marked_failed() -> None:
    from backend.models import TaskStatus
    from backend.services.task_service import TaskService

    service = TaskService()
    task = SimpleNamespace(
        id="task-canceled-by-adapter",
        provider="opencode",
        status=TaskStatus.RUNNING.value,
        payload_json={},
    )
    db = SimpleNamespace(refresh=AsyncMock())
    service.update_status = AsyncMock()
    service._mark_conversation_completion_failed = AsyncMock()
    service.append_log = AsyncMock()

    preserved = await service._preserve_canceled_task(
        db,
        task,
        {"canceled": True, "diagnostic": "task canceled"},
    )

    assert preserved is True
    service.update_status.assert_awaited_once_with(
        db,
        task,
        TaskStatus.CANCELED,
        error="Canceled by user",
    )
    service._mark_conversation_completion_failed.assert_awaited_once_with(db, task, "任务已取消")
    service.append_log.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_develop_task_does_not_overwrite_concurrent_cancel() -> None:
    from backend.services.task_service import TaskService

    service = TaskService()
    task = SimpleNamespace(id="task-cancel-race", provider="opencode")
    db = SimpleNamespace(get=AsyncMock(return_value=task))
    service._run_develop_task_for_provider = AsyncMock(side_effect=RuntimeError("task canceled"))
    service._preserve_canceled_task = AsyncMock(return_value=True)
    service._mark_conversation_completion_failed = AsyncMock()
    service.append_log = AsyncMock()
    service.update_status = AsyncMock()

    result = await service.run_develop_task(db, str(task.id))

    assert result is task
    service._mark_conversation_completion_failed.assert_not_awaited()
    service.update_status.assert_not_awaited()
