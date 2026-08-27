from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.runtime import AgentRuntime
from app.agent.state import SessionState
from app.api import AppServices, create_app
from app.config import ModelConfigurationStatus
from app.providers.fake import FakeProvider
from app.providers.types import AssistantTurn, ToolCall
from app.safety.approval import ApprovalService
from app.tools.defaults import build_file_tool_registry


def ready() -> ModelConfigurationStatus:
    return ModelConfigurationStatus(ready=True, summary={})


def wait_for_status(client: TestClient, session_id: str, statuses: set[str]) -> dict:
    for _ in range(300):
        snapshot = client.get(f"/api/sessions/{session_id}").json()
        if snapshot["status"] in statuses:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("status did not change")


def test_approval_endpoint_resumes_bound_command_and_rejects_replay(tmp_path: Path) -> None:
    target = tmp_path / "generated.txt"
    target.write_text("remove me")
    approval_service = ApprovalService()
    arguments = {"command": "rm generated.txt", "timeout_seconds": 60.0}
    call = ToolCall(
        id="delete-call",
        name="run_command",
        raw_arguments=json.dumps(arguments),
        arguments=arguments,
    )

    def runtime_factory(_state: SessionState) -> AgentRuntime:
        provider = FakeProvider(
            AssistantTurn(tool_calls=(call,)),
            AssistantTurn(content="deleted"),
        )
        return AgentRuntime(
            provider,
            build_file_tool_registry(approval_service=approval_service),
            system_prompt="system",
        )

    services = AppServices(
        approval_service=approval_service,
        runtime_factory=runtime_factory,
        config_inspector=ready,
    )
    app = create_app(services)
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"workspace": str(tmp_path)}).json()
        session_id = session["session_id"]
        client.post(f"/api/sessions/{session_id}/tasks", json={"task": "delete"})
        waiting = wait_for_status(client, session_id, {"waiting_approval"})
        approval = waiting["pending_approvals"][0]
        resolved = client.post(
            f"/api/sessions/{session_id}/approvals/{approval['approval_id']}",
            json={"approved": True},
        )
        completed = wait_for_status(client, session_id, {"completed", "failed"})
        replay = client.post(
            f"/api/sessions/{session_id}/approvals/{approval['approval_id']}",
            json={"approved": True},
        )

    assert resolved.status_code == 200
    assert resolved.json()["status"] == "approved"
    assert completed["status"] == "completed"
    assert not target.exists()
    assert replay.status_code == 409


def test_cross_session_approval_and_cancel_are_safe_and_idempotent(tmp_path: Path) -> None:
    approval_service = ApprovalService()
    services = AppServices(approval_service=approval_service, config_inspector=ready)
    app = create_app(services)
    with TestClient(app) as client:
        owner = client.post("/api/sessions", json={"workspace": str(tmp_path)}).json()
        other = client.post("/api/sessions", json={"workspace": str(tmp_path)}).json()
        first_cancel = client.post(f"/api/sessions/{other['session_id']}/cancel")
        second_cancel = client.post(f"/api/sessions/{other['session_id']}/cancel")
        missing_approval = client.post(
            f"/api/sessions/{owner['session_id']}/approvals/not-found",
            json={"approved": True},
        )

    assert first_cancel.status_code == 200
    assert second_cancel.status_code == 200
    assert first_cancel.json()["status"] == "cancelled"
    assert second_cancel.json()["status"] == "cancelled"
    assert missing_approval.status_code == 409

