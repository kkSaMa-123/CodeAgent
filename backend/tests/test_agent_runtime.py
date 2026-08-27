from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.agent.runtime import AgentRuntime, RuntimeLimits
from app.agent.state import SessionState, SessionStatus, TerminationReason
from app.agent.tools import MappingToolExecutor, ToolExecutionResult
from app.providers.errors import ProviderError, ProviderErrorKind
from app.providers.fake import FakeProvider
from app.providers.types import AssistantTurn, ToolCall


def call(call_id: str, name: str, arguments: dict[str, str]) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        raw_arguments=json.dumps(arguments),
        arguments=arguments,
    )


def make_state(tmp_path: Path) -> SessionState:
    return SessionState(session_id="test-session", workspace=tmp_path)


def test_final_answer_completes_without_tools(tmp_path: Path) -> None:
    provider = FakeProvider(AssistantTurn(content="任务已完成"))
    tools = MappingToolExecutor({})
    runtime = AgentRuntime(provider, tools, system_prompt="system")
    state = asyncio.run(runtime.run(make_state(tmp_path), "task"))

    assert state.status is SessionStatus.COMPLETED
    assert state.termination_reason is TerminationReason.COMPLETED
    assert state.final_answer == "任务已完成"
    assert [message.role for message in state.messages] == ["system", "user", "assistant"]


def test_single_tool_result_is_paired_with_call_id(tmp_path: Path) -> None:
    read_call = call("call-read", "read_file", {"path": "README.md"})
    provider = FakeProvider(
        AssistantTurn(tool_calls=(read_call,)),
        AssistantTurn(content="read complete"),
    )
    tools = MappingToolExecutor(
        {"read_file": lambda _call, _context: ToolExecutionResult.success("content")}
    )
    runtime = AgentRuntime(provider, tools, system_prompt="system")
    state = asyncio.run(runtime.run(make_state(tmp_path), "task"))

    tool_message = state.messages[3]
    assert tool_message.role == "tool"
    assert tool_message.tool_call_id == "call-read"
    assert json.loads(tool_message.content or "")["output"] == "content"
    assert provider.calls[1][0][-1] == tool_message


def test_multiple_tools_keep_order_and_pairing(tmp_path: Path) -> None:
    calls = (
        call("call-one", "read_file", {"path": "one.py"}),
        call("call-two", "read_file", {"path": "two.py"}),
    )
    execution_order: list[str] = []

    def execute(tool_call: ToolCall, _context: object) -> ToolExecutionResult:
        execution_order.append(tool_call.id)
        path = tool_call.arguments["path"] if tool_call.arguments else ""
        return ToolExecutionResult.success(path)

    provider = FakeProvider(AssistantTurn(tool_calls=calls), AssistantTurn(content="done"))
    tools = MappingToolExecutor({"read_file": execute})
    runtime = AgentRuntime(provider, tools, system_prompt="system")
    state = asyncio.run(runtime.run(make_state(tmp_path), "task"))

    assert execution_order == ["call-one", "call-two"]
    assert [message.tool_call_id for message in state.messages if message.role == "tool"] == [
        "call-one",
        "call-two",
    ]


def test_tool_error_is_observation_and_model_can_recover(tmp_path: Path) -> None:
    missing_call = call("call-missing", "read_file", {"path": "missing.py"})
    corrected_call = call("call-correct", "read_file", {"path": "main.py"})
    provider = FakeProvider(
        AssistantTurn(tool_calls=(missing_call,)),
        AssistantTurn(tool_calls=(corrected_call,)),
        AssistantTurn(content="found it"),
    )

    def read_file(tool_call: ToolCall, _context: object) -> ToolExecutionResult:
        path = tool_call.arguments["path"] if tool_call.arguments else ""
        if path == "missing.py":
            return ToolExecutionResult.error(
                "文件不存在: missing.py",
                error_type="file_not_found",
            )
        return ToolExecutionResult.success("print('ok')")

    runtime = AgentRuntime(
        provider,
        MappingToolExecutor({"read_file": read_file}),
        system_prompt="system",
    )
    state = asyncio.run(runtime.run(make_state(tmp_path), "find main"))
    tool_messages = [message for message in state.messages if message.role == "tool"]

    assert state.status is SessionStatus.COMPLETED
    assert len(provider.calls) == 3
    assert [message.tool_call_id for message in tool_messages] == ["call-missing", "call-correct"]
    assert json.loads(tool_messages[0].content or "")["error_type"] == "file_not_found"
    assert json.loads(tool_messages[1].content or "")["status"] == "success"


def test_max_iterations_has_explicit_reason(tmp_path: Path) -> None:
    provider = FakeProvider(AssistantTurn(tool_calls=(call("repeat", "noop", {}),)))
    runtime = AgentRuntime(
        provider,
        MappingToolExecutor({"noop": lambda _call, _context: ToolExecutionResult.success("ok")}),
        system_prompt="system",
        limits=RuntimeLimits(max_iterations=1),
    )
    state = asyncio.run(runtime.run(make_state(tmp_path), "never finish"))

    assert state.status is SessionStatus.FAILED
    assert state.termination_reason is TerminationReason.MAX_ITERATIONS


def test_total_timeout_cancels_active_provider(tmp_path: Path) -> None:
    cancelled = False

    async def scenario() -> SessionState:
        nonlocal cancelled

        class SlowProvider:
            async def complete(self, messages: object, tools: object = ()) -> AssistantTurn:
                nonlocal cancelled
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    cancelled = True
                    raise
                return AssistantTurn(content="too late")

        runtime = AgentRuntime(
            SlowProvider(),  # type: ignore[arg-type]
            MappingToolExecutor({}),
            system_prompt="system",
            limits=RuntimeLimits(task_timeout_seconds=0.01),
        )
        return await runtime.run(make_state(tmp_path), "timeout")

    state = asyncio.run(scenario())
    assert state.status is SessionStatus.FAILED
    assert state.termination_reason is TerminationReason.TASK_TIMEOUT
    assert cancelled


def test_user_cancel_interrupts_active_provider(tmp_path: Path) -> None:
    async def scenario() -> SessionState:
        started = asyncio.Event()

        class WaitingProvider:
            async def complete(self, messages: object, tools: object = ()) -> AssistantTurn:
                started.set()
                await asyncio.sleep(60)
                return AssistantTurn(content="too late")

        state = make_state(tmp_path)
        runtime = AgentRuntime(
            WaitingProvider(),  # type: ignore[arg-type]
            MappingToolExecutor({}),
            system_prompt="system",
        )
        running = asyncio.create_task(runtime.run(state, "cancel"))
        await started.wait()
        state.request_cancel()
        return await running

    state = asyncio.run(scenario())
    assert state.status is SessionStatus.CANCELLED
    assert state.termination_reason is TerminationReason.CANCELLED


def test_provider_error_has_specific_termination_reason(tmp_path: Path) -> None:
    provider = FakeProvider(
        ProviderError(
            ProviderErrorKind.AUTHENTICATION,
            "unsafe provider detail",
            retryable=False,
        )
    )
    runtime = AgentRuntime(provider, MappingToolExecutor({}), system_prompt="system")
    state = asyncio.run(runtime.run(make_state(tmp_path), "fail safely"))

    assert state.status is SessionStatus.FAILED
    assert state.termination_reason is TerminationReason.PROVIDER_ERROR
    error_event = next(
        event for event in state.events.snapshot() if event.event_type == "model.error"
    )
    assert error_event.payload == {"kind": "authentication_error", "retryable": False}
