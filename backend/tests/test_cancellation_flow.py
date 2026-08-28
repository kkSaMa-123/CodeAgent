from __future__ import annotations

import asyncio
import json
import shlex
import sys
from pathlib import Path

from app.agent.runtime import AgentRuntime
from app.agent.state import SessionState, SessionStatus, TerminationReason
from app.providers.fake import FakeProvider
from app.providers.types import AssistantTurn, ToolCall
from app.safety.approval import ApprovalService, ApprovalStatus
from app.tools.defaults import build_file_tool_registry


def tool_call(call_id: str, command: str, timeout: float = 10) -> ToolCall:
    arguments = {"command": command, "timeout_seconds": timeout}
    return ToolCall(
        id=call_id,
        name="run_command",
        raw_arguments=json.dumps(arguments),
        arguments=arguments,
    )


def test_cancelled_before_start_never_calls_model(tmp_path: Path) -> None:
    provider = FakeProvider(AssistantTurn(content="should not run"))
    state = SessionState("queued-cancel", tmp_path)
    state.request_cancel()

    result = asyncio.run(
        AgentRuntime(provider, build_file_tool_registry(), system_prompt="system").run(
            state,
            "task",
        )
    )

    assert result.status is SessionStatus.CANCELLED
    assert result.termination_reason is TerminationReason.CANCELLED
    assert provider.calls == []


def test_cancel_while_waiting_approval_invalidates_request(tmp_path: Path) -> None:
    async def scenario() -> tuple[SessionState, ApprovalStatus]:
        service = ApprovalService()
        provider = FakeProvider(
            AssistantTurn(tool_calls=(tool_call("delete", "rm generated.txt"),))
        )
        state = SessionState("approval-cancel", tmp_path)
        runtime = AgentRuntime(
            provider,
            build_file_tool_registry(approval_service=service),
            system_prompt="system",
        )
        running = asyncio.create_task(runtime.run(state, "delete"))
        while state.status is not SessionStatus.WAITING_APPROVAL:
            await asyncio.sleep(0.01)
        pending = (await service.list_pending(state.session_id))[0]
        state.request_cancel()
        result = await running
        return result, (await service.get(pending.approval_id)).status

    state, approval_status = asyncio.run(scenario())

    assert state.status is SessionStatus.CANCELLED
    assert approval_status is ApprovalStatus.CANCELLED
    assert not (tmp_path / "generated.txt").exists()


def test_cancel_running_command_prevents_delayed_side_effect(tmp_path: Path) -> None:
    sleeper = tmp_path / "test_sleeper.py"
    marker = tmp_path / "marker.txt"
    sleeper.write_text(
        "import time\n"
        "from pathlib import Path\n\n"
        "def test_delayed_write():\n"
        "    time.sleep(2)\n"
        "    Path('marker.txt').write_text('late')\n"
    )

    async def scenario() -> SessionState:
        command = f"{shlex.quote(sys.executable)} -m pytest -q test_sleeper.py"
        provider = FakeProvider(AssistantTurn(tool_calls=(tool_call("test", command),)))
        state = SessionState("command-cancel", tmp_path)
        runtime = AgentRuntime(provider, build_file_tool_registry(), system_prompt="system")
        running = asyncio.create_task(runtime.run(state, "run test"))
        while not any(event.event_type == "tool.started" for event in state.events.snapshot()):
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)
        state.request_cancel()
        return await running

    state = asyncio.run(scenario())

    assert state.status is SessionStatus.CANCELLED
    assert state.termination_reason is TerminationReason.CANCELLED
    assert not marker.exists()
