from __future__ import annotations

from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_mcp_service_can_be_enabled_and_tested(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    list_response = await client.get("/api/v2/mcp/services", headers=auth_headers)
    assert list_response.status_code == 200
    assert any(item["service_id"] == "context7" for item in list_response.json()["services"])

    bad_response = await client.put(
        "/api/v2/mcp/services/exa",
        json={"enabled": True, "config": {}},
        headers=auth_headers,
    )
    assert bad_response.status_code == 400

    update_response = await client.put(
        "/api/v2/mcp/services/exa",
        json={"enabled": True, "config": {"api_key": "exa-key"}},
        headers=auth_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["service"]["enabled"] is True

    test_response = await client.post("/api/v2/mcp/services/exa/test", headers=auth_headers)
    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True


@pytest.mark.asyncio
async def test_skill_markdown_import_and_binding(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    await client.post(
        "/api/v2/sites",
        json={"site_id": "skill-site", "name": "Skill Site", "auto_start": False},
        headers=auth_headers,
    )

    import_response = await client.post(
        "/api/v2/skills/import",
        json={
            "type": "markdown",
            "markdown": "# Vue Helper\n\n用于 Vue 组件拆分。",
        },
        headers=auth_headers,
    )
    assert import_response.status_code == 200
    skill_id = import_response.json()["skill"]["id"]

    bind_response = await client.post(
        f"/api/v2/skills/{skill_id}/bind-site",
        json={"site_id": "skill-site", "bind": True},
        headers=auth_headers,
    )
    assert bind_response.status_code == 200
    assert "skill-site" in bind_response.json()["skill"]["bound_site_ids"]

    site_response = await client.get("/api/v2/skills/site/skill-site", headers=auth_headers)
    assert site_response.status_code == 200
    assert site_response.json()["skills"][0]["name"] == "Vue Helper"


@pytest.mark.asyncio
async def test_skill_can_import_from_skills_sh(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_import(url: str) -> dict[str, object]:
        return {
            "name": "vue-best-practices",
            "description": "Imported from skills.sh",
            "content": "# vue-best-practices\n\nUse Vue 3.",
            "triggers": ["vue", "skills.sh"],
        }

    from backend.services.skill_service import skill_service

    monkeypatch.setattr(skill_service, "_import_from_skills_sh", fake_import)

    response = await client.post(
        "/api/v2/skills/import",
        json={
            "type": "skills_sh",
            "url": "https://skills.sh/hyf0/vue-skills/vue-best-practices",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()["skill"]
    assert payload["source_type"] == "skills.sh"
    assert payload["source_url"] == "https://skills.sh/hyf0/vue-skills/vue-best-practices"


@pytest.mark.asyncio
async def test_workflow_run_writes_artifacts_under_np(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    app_module,
) -> None:
    await client.post(
        "/api/v2/sites",
        json={"site_id": "wf-site", "name": "Workflow Site", "auto_start": False},
        headers=auth_headers,
    )

    create_response = await client.post(
        "/api/v2/workflows/sites/wf-site/runs",
        json={"name": "首页改版"},
        headers=auth_headers,
    )
    assert create_response.status_code == 200
    run = create_response.json()["run"]

    generate_response = await client.post(
        f"/api/v2/workflows/runs/{run['id']}/generate-stage",
        json={"stage": "research", "content": "# 研究\n\n梳理现状与目标"},
        headers=auth_headers,
    )
    assert generate_response.status_code == 200

    artifact_path = app_module.site_service.site_root("wf-site") / ".np" / "workflows" / "runs" / run["id"] / "research.md"
    current_index = app_module.site_service.site_root("wf-site") / ".np" / "workflows" / "current" / "wf-site.json"
    assert artifact_path.exists()
    assert current_index.exists()
    assert "梳理现状与目标" in artifact_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_workflow_stage_blocks_and_allows_task_creation(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    await client.post(
        "/api/v2/sites",
        json={"site_id": "wf-task-site", "name": "Workflow Task Site", "auto_start": False},
        headers=auth_headers,
    )
    run_response = await client.post(
        "/api/v2/workflows/sites/wf-task-site/runs",
        json={"name": "执行约束"},
        headers=auth_headers,
    )
    run_id = run_response.json()["run"]["id"]

    blocked = await client.post(
        "/api/v2/tasks",
        json={
            "site_id": "wf-task-site",
            "task_type": "develop_code",
            "provider": "codex",
            "prompt": "先别执行",
            "workflow_run_id": run_id,
        },
        headers=auth_headers,
    )
    assert blocked.status_code == 409

    for stage in ("research", "ideate", "plan"):
      save_response = await client.post(
          f"/api/v2/workflows/runs/{run_id}/generate-stage",
          json={"stage": stage, "content": f"# {stage}\n\ncontent"},
          headers=auth_headers,
      )
      assert save_response.status_code == 200
      confirm_response = await client.post(
          f"/api/v2/workflows/runs/{run_id}/confirm-stage",
          headers=auth_headers,
      )
      assert confirm_response.status_code == 200

    allowed = await client.post(
        "/api/v2/tasks",
        json={
            "site_id": "wf-task-site",
            "task_type": "develop_code",
            "provider": "codex",
            "prompt": "现在可以执行",
            "workflow_run_id": run_id,
        },
        headers=auth_headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["task"]["payload"]["workflow_stage"] == "execute"
