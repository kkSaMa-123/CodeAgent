from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.agent.repetition import RepetitionDecision, RepetitionGuard, tool_call_signature
from app.agent.runtime import AgentRuntime, RuntimeLimits
from app.agent.state import SessionState, SessionStatus, TerminationReason
from app.agent.tools import MappingToolExecutor, ToolExecutionResult
from app.providers.fake import FakeProvider
from app.providers.types import AssistantTurn, ToolCall


def make_call(call_id: str, name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        raw_arguments=json.dumps(arguments),
        arguments=arguments,
    )


def test_signature_normalizes_argument_order_and_includes_workspace_version() -> None:
    first = make_call("one", "read_file", {"path": "a.py", "start": 1})
    second = make_call("two", "read_file", {"start": 1, "path": "a.py"})

    assert tool_call_signature(first, 0) == tool_call_signature(second, 0)
    assert tool_call_signature(first, 0) != tool_call_signature(second, 1)


def test_guard_warns_then_stops_consecutive_no_progress_calls() -> None:
    guard = RepetitionGuard(warning_threshold=3, stop_threshold=5)
    decisions = [
        guard.check(make_call(str(index), "read_file", {"path": "same.py"}), 0)
        for index in range(5)
    ]

    assert decisions == [
        RepetitionDecision.ALLOW,
        RepetitionDecision.ALLOW,
        RepetitionDecision.WARN,
        RepetitionDecision.WARN,
        RepetitionDecision.STOP,
    ]


def test_runtime_limits_repeated_call_and_returns_warning_observations(tmp_path: Path) -> None:
    repeated_turns = [
        AssistantTurn(tool_calls=(make_call(str(index), "read_file", {"path": "same.py"}),))
        for index in range(5)
    ]
    provider = FakeProvider(*repeated_turns)
    executions = 0

    def read(_call: ToolCall, _context: object) -> ToolExecutionResult:
        nonlocal executions
        executions += 1
        return ToolExecutionResult.success("unchanged")

    runtime = AgentRuntime(
        provider,
        MappingToolExecutor({"read_file": read}),
        system_prompt="system",
        limits=RuntimeLimits(max_iterations=10),
    )
    state = asyncio.run(runtime.run(SessionState("repeat", tmp_path), "read repeatedly"))
    warnings = [
        json.loads(message.content or "")
        for message in state.messages
        if message.role == "tool" and "repeated_tool_call" in (message.content or "")
    ]

    assert executions == 2
    assert len(warnings) == 2
    assert state.status is SessionStatus.FAILED
    assert state.termination_reason is TerminationReason.REPEATED_TOOL_CALL


def test_workspace_change_allows_same_read_again(tmp_path: Path) -> None:
    turns = (
        AssistantTurn(tool_calls=(make_call("read-1", "read_file", {"path": "a.py"}),)),
        AssistantTurn(tool_calls=(make_call("write", "write_file", {"path": "a.py"}),)),
        AssistantTurn(tool_calls=(make_call("read-2", "read_file", {"path": "a.py"}),)),
        AssistantTurn(content="done"),
    )
    reads = 0

    def read(_call: ToolCall, _context: object) -> ToolExecutionResult:
        nonlocal reads
        reads += 1
        return ToolExecutionResult.success("content")

    tools = MappingToolExecutor(
        {
            "read_file": read,
            "write_file": lambda _call, _context: ToolExecutionResult.success(
                "written",
                modified_files=("a.py",),
                workspace_changed=True,
            ),
        }
    )
    runtime = AgentRuntime(FakeProvider(*turns), tools, system_prompt="system")
    state = asyncio.run(runtime.run(SessionState("version", tmp_path), "edit then read"))

    assert state.status is SessionStatus.COMPLETED
    assert state.workspace_version == 1
    assert reads == 2

