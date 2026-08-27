from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.agent.context import ContextWindow, estimate_context_chars, truncate_text
from app.agent.runtime import AgentRuntime, RuntimeLimits
from app.agent.state import SessionState
from app.agent.tools import MappingToolExecutor, ToolExecutionResult
from app.providers.fake import FakeProvider
from app.providers.types import AssistantTurn, ChatMessage, ToolCall


def make_call(call_id: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="read_file",
        raw_arguments='{"path":"x"}',
        arguments={"path": "x"},
    )


def test_truncate_text_preserves_head_tail_and_length_marker() -> None:
    original = "HEAD" + "x" * 1_000 + "TAIL"
    truncated = truncate_text(original, 120)

    assert len(truncated) == 120
    assert truncated.startswith("HEAD")
    assert truncated.endswith("TAIL")
    assert "已截断" in truncated
    assert f"原始长度 {len(original)} 字符" in truncated
    assert "省略" in truncated


def test_history_budget_keeps_original_task_and_complete_latest_pair() -> None:
    old_call = make_call("old")
    current_calls = (make_call("current-a"), make_call("current-b"))
    messages = [
        ChatMessage.system("system constraints"),
        ChatMessage.user("ORIGINAL TASK"),
        ChatMessage(role="assistant", tool_calls=(old_call,)),
        ChatMessage.tool("o" * 500, "old"),
        ChatMessage(role="assistant", content="discardable history" * 20),
        ChatMessage(role="assistant", tool_calls=current_calls),
        ChatMessage.tool("current result a", "current-a"),
    ]

    prepared = ContextWindow(budget_chars=250).prepare(messages)

    assert messages[0] in prepared
    assert messages[1] in prepared
    assert messages[-2] in prepared
    assert messages[-1] in prepared
    assert all(message.tool_call_id != "old" for message in prepared)
    assert estimate_context_chars(prepared) <= 250


def test_runtime_limits_tool_output_before_history_and_provider(tmp_path: Path) -> None:
    tool_call = make_call("long-output")
    provider = FakeProvider(
        AssistantTurn(tool_calls=(tool_call,)),
        AssistantTurn(content="done"),
    )
    runtime = AgentRuntime(
        provider,
        MappingToolExecutor(
            {"read_file": lambda _call, _context: ToolExecutionResult.success("A" * 1_000 + "END")}
        ),
        system_prompt="system",
        limits=RuntimeLimits(max_tool_output_chars=100),
    )
    state = SessionState(session_id="context", workspace=tmp_path)

    asyncio.run(runtime.run(state, "task"))

    stored = next(message for message in state.messages if message.role == "tool")
    output = json.loads(stored.content or "")["output"]
    assert len(output) == 100
    assert output.endswith("END")
    assert "已截断" in output
    assert provider.calls[1][0][-1] == stored
