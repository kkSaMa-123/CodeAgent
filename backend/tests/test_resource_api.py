from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.runtime import AgentRuntime
from app.agent.state import RunState
from app.api import AppServices, create_app
from app.config import ModelConfigurationStatus
from app.persistence import SQLiteRepository
from app.providers.fake import FakeProvider
from app.providers.types import AssistantTurn
from app.tools.defaults import build_file_tool_registry


def ready() -> ModelConfigurationStatus:
    return ModelConfigurationStatus(ready=True, summary={})


def services(tmp_path: Path, provider: FakeProvider | None = None) -> AppServices:
    def runtime_factory(_state: RunState) -> AgentRuntime:
        return AgentRuntime(
            provider or FakeProvider(AssistantTurn(content="完成")),
            build_file_tool_registry(),
            system_prompt="system",
        )

    return AppServices(
        repository=SQLiteRepository(tmp_path / "history.sqlite3"),
        runtime_factory=runtime_factory,
        config_inspector=ready,
    )


def wait(client: TestClient, run_id: str) -> dict:
    for _ in range(200):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def test_project_conversation_multiturn_refresh_and_safe_metadata_delete(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = workspace / "keep.txt"
    marker.write_text("keep")
    provider = FakeProvider(AssistantTurn(content="第一轮"), AssistantTurn(content="第二轮"))
    app = create_app(services(tmp_path, provider))
    with TestClient(app) as client:
        project = client.post(
            "/api/projects", json={"workspace": str(workspace), "name": "Demo"}
        ).json()
        duplicate = client.post("/api/projects", json={"workspace": str(workspace / ".")}).json()
        assert duplicate["id"] == project["id"]
        conversation = client.post(f"/api/projects/{project['id']}/conversations", json={}).json()
        first = client.post(
            f"/api/conversations/{conversation['id']}/runs", json={"task": "第一项任务"}
        ).json()
        assert wait(client, first["id"])["status"] == "completed"
        second = client.post(
            f"/api/conversations/{conversation['id']}/runs", json={"task": "继续完善"}
        ).json()
        assert wait(client, second["id"])["status"] == "completed"
        messages = client.get(f"/api/conversations/{conversation['id']}/messages").json()
        assert [item["content"] for item in messages] == [
            "第一项任务",
            "第一轮",
            "继续完善",
            "第二轮",
        ]
        assert (
            client.get(
                f"/api/projects/{project['id']}/files/content", params={"path": "keep.txt"}
            ).status_code
            == 200
        )
        assert client.get("/api/sessions/anything").status_code == 404
        assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert marker.read_text() == "keep"


def test_resource_ownership_history_changes_and_sse(tmp_path: Path) -> None:
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()
    app = create_app(services(tmp_path))
    with TestClient(app) as client:
        first = client.post("/api/projects", json={"workspace": str(first_workspace)}).json()
        second = client.post("/api/projects", json={"workspace": str(second_workspace)}).json()
        conversation = client.post(f"/api/projects/{first['id']}/conversations", json={}).json()
        run = client.post(
            f"/api/conversations/{conversation['id']}/runs", json={"task": "完成"}
        ).json()
        wait(client, run["id"])
        assert client.get(f"/api/runs/{run['id']}/changes").status_code == 200
        history = client.get(f"/api/runs/{run['id']}/events/history")
        assert history.status_code == 200
        assert history.json()[-1]["event_type"] == "task.completed"
        assert history.json()[-1]["run_id"] == run["id"]
        assert client.get(f"/api/runs/{run['id']}/events").text.count("event: task.completed") == 1
        assert (
            client.get(
                f"/api/projects/{second['id']}/files/content", params={"path": "../first"}
            ).status_code
            == 400
        )


def test_tool_and_skill_configuration_api(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: api-review\ndescription: API 测试\nrequired_tools:\n  - read_file\n"
        "---\n\n只读取并审查代码。",
        encoding="utf-8",
    )
    app = create_app(services(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"workspace": str(workspace)}).json()
        conversation = client.post(
            f"/api/projects/{project['id']}/conversations", json={}
        ).json()
        tools = client.get("/api/capabilities/tools").json()
        assert {item["name"] for item in tools} >= {"read_file", "run_command"}
        skill = client.post("/api/skills", json={"path": str(skill_dir)}).json()
        configured = client.put(
            f"/api/conversations/{conversation['id']}/capabilities",
            json={"enabled_tools": ["read_file"], "enabled_skills": [skill["id"]]},
        ).json()
        assert configured["enabled_tools"] == ["read_file"]
        run = client.post(
            f"/api/conversations/{conversation['id']}/runs", json={"task": "审查"}
        ).json()
        wait(client, run["id"])
        snapshot = client.get(f"/api/runs/{run['id']}/capabilities").json()
        assert snapshot["enabled_tools"] == ["read_file"]
        assert snapshot["skills"][0]["name"] == "api-review"
