from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.runtime import AgentRuntime
from app.agent.state import SessionState
from app.api import AppServices, create_app
from app.config import ModelConfigurationStatus
from app.providers.fake import FakeProvider
from app.providers.types import AssistantTurn
from app.tools.defaults import build_file_tool_registry


def ready() -> ModelConfigurationStatus:
    return ModelConfigurationStatus(ready=True, summary={})


def wait_for_terminal(client: TestClient, session_id: str) -> dict:
    for _ in range(200):
        snapshot = client.get(f"/api/sessions/{session_id}").json()
        if snapshot["status"] in {"completed", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("task did not finish")


class SlowProvider:
    async def complete(self, messages, tools=()):
        import asyncio

        await asyncio.sleep(0.3)
        return AssistantTurn(content="slow done")


def test_duplicate_task_and_concurrency_limit(tmp_path: Path) -> None:
    def runtime_factory(_state: SessionState) -> AgentRuntime:
        return AgentRuntime(SlowProvider(), build_file_tool_registry(), system_prompt="system")

    services = AppServices(
        runtime_factory=runtime_factory,
        config_inspector=ready,
        max_concurrent_tasks=1,
    )
    app = create_app(services)
    with TestClient(app) as client:
        first = client.post("/api/sessions", json={"workspace": str(tmp_path)}).json()
        second = client.post("/api/sessions", json={"workspace": str(tmp_path)}).json()
        accepted = client.post(f"/api/sessions/{first['session_id']}/tasks", json={"task": "one"})
        duplicate = client.post(
            f"/api/sessions/{first['session_id']}/tasks",
            json={"task": "again"},
        )
        limited = client.post(
            f"/api/sessions/{second['session_id']}/tasks",
            json={"task": "two"},
        )

        assert accepted.status_code == 202
        assert duplicate.status_code == 409
        assert limited.status_code == 429
        assert wait_for_terminal(client, first["session_id"])["status"] == "completed"


def test_different_sessions_run_in_isolation(tmp_path: Path) -> None:
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()

    def runtime_factory(state: SessionState) -> AgentRuntime:
        provider = FakeProvider(AssistantTurn(content=f"done:{state.workspace.name}"))
        return AgentRuntime(provider, build_file_tool_registry(), system_prompt="system")

    app = create_app(
        AppServices(runtime_factory=runtime_factory, config_inspector=ready, max_concurrent_tasks=2)
    )
    with TestClient(app) as client:
        first = client.post("/api/sessions", json={"workspace": str(first_workspace)}).json()
        second = client.post("/api/sessions", json={"workspace": str(second_workspace)}).json()
        client.post(f"/api/sessions/{first['session_id']}/tasks", json={"task": "one"})
        client.post(f"/api/sessions/{second['session_id']}/tasks", json={"task": "two"})
        first_done = wait_for_terminal(client, first["session_id"])
        second_done = wait_for_terminal(client, second["session_id"])

    assert first_done["final_answer"] == "done:first"
    assert second_done["final_answer"] == "done:second"
    assert first_done["workspace"] != second_done["workspace"]

