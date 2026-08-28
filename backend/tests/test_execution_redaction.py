from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.agent.state import SessionState
from app.agent.tools import ToolExecutionContext
from app.providers.redaction import REDACTED, SecretRedactor
from app.providers.types import ToolCall
from app.tools.base import ToolArguments, ToolContext, ToolResult
from app.tools.registry import ToolRegistry

SECRET = "sk-super-secret-value"


class LeakingTool:
    name = "leak"
    description = "test"

    class Arguments(ToolArguments):
        pass

    arguments_model = Arguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        return ToolResult.success(
            f"token={SECRET}",
            output=f"Authorization: Bearer {SECRET}",
            metadata={"nested": {"api_key": SECRET}},
        )


class ExplodingTool(LeakingTool):
    name = "explode"

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        raise RuntimeError(f"failed with {SECRET}")


def make_call(name: str) -> ToolCall:
    return ToolCall(id="call", name=name, raw_arguments="{}", arguments={})


def test_event_payload_is_recursively_redacted(tmp_path: Path) -> None:
    state = SessionState("redacted", tmp_path)
    event = state.publish(
        "test.secret",
        {
            "output": f"Authorization: Bearer {SECRET}",
            "nested": {"token": SECRET},
        },
    )

    assert SECRET not in repr(event.payload)
    assert REDACTED in repr(event.payload)


def test_tool_output_and_metadata_are_redacted_before_history(tmp_path: Path) -> None:
    redactor = SecretRedactor([SECRET])
    registry = ToolRegistry([LeakingTool()], redactor=redactor)
    context = ToolExecutionContext("session", tmp_path, lambda: False)

    result = asyncio.run(registry.execute(make_call("leak"), context))

    assert SECRET not in result.to_message_content()
    assert REDACTED in result.to_message_content()


def test_internal_exception_log_is_redacted(
    tmp_path: Path,
    caplog,
) -> None:
    registry = ToolRegistry([ExplodingTool()], redactor=SecretRedactor([SECRET]))
    context = ToolExecutionContext("session", tmp_path, lambda: False)

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(registry.execute(make_call("explode"), context))

    assert result.error_type == "internal_tool_error"
    assert SECRET not in caplog.text
    assert REDACTED in caplog.text
