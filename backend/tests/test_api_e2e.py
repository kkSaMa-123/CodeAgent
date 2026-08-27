from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.runtime import AgentRuntime
from app.agent.state import SessionState
from app.api import AppServices, create_app
from app.config import ModelConfigurationStatus
from app.providers.fake import FakeProvider
from app.providers.types import AssistantTurn, ToolCall
from app.tools.defaults import build_file_tool_registry


def ready() -> ModelConfigurationStatus:
    return ModelConfigurationStatus(ready=True, summary={})


def call(call_id: str, name: str, arguments: dict) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        raw_arguments=json.dumps(arguments),
        arguments=arguments,
    )


def test_fake_provider_completes_http_tool_and_event_loop(tmp_path: Path) -> None:
    (tmp_path / "test_app.py").write_text(
        "from app import add\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
    )
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "test_app.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "initial"],
        check=True,
    )
    provider = FakeProvider(
        AssistantTurn(
            tool_calls=(
                call(
                    "write",
                    "write_file",
                    {"path": "app.py", "content": "def add(a, b):\n    return a + b\n"},
                ),
            )
        ),
        AssistantTurn(
            tool_calls=(
                call(
                    "test",
                    "run_command",
                    {"command": f"{sys.executable} -m pytest -q", "timeout_seconds": 20},
                ),
            )
        ),
        AssistantTurn(content="Implemented add() and verified the tests."),
    )

    def runtime_factory(_state: SessionState) -> AgentRuntime:
        return AgentRuntime(provider, build_file_tool_registry(), system_prompt="system")

    app = create_app(AppServices(runtime_factory=runtime_factory, config_inspector=ready))
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"workspace": str(tmp_path)}).json()
        session_id = session["session_id"]
        submitted = client.post(
            f"/api/sessions/{session_id}/tasks",
            json={"task": "Implement add and run tests"},
        )
        for _ in range(500):
            snapshot = client.get(f"/api/sessions/{session_id}").json()
            if snapshot["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        events = client.get(f"/api/sessions/{session_id}/events")
        diff = client.get(f"/api/sessions/{session_id}/diff")

    assert submitted.status_code == 202
    assert snapshot["status"] == "completed"
    assert snapshot["final_answer"] == "Implemented add() and verified the tests."
    assert snapshot["modified_files"] == ["app.py"]
    assert (tmp_path / "app.py").read_text().startswith("def add")
    assert events.text.count("event: tool.started") == 2
    assert events.text.count("event: tool.completed") == 2
    assert "event: task.completed" in events.text
    assert "+def add(a, b):" in diff.json()["diff"]

