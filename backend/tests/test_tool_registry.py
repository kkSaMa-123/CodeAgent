from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import Field

from app.agent.tools import ToolExecutionContext
from app.providers.types import ToolCall
from app.tools import ToolArguments, ToolContext, ToolRegistry, ToolResult


class EchoArguments(ToolArguments):
    text: str = Field(min_length=1)


class EchoTool:
    name = "echo"
    description = "Return text"
    arguments_model = EchoArguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        parsed = EchoArguments.model_validate(arguments)
        return ToolResult.success(
            "echoed",
            output=parsed.text,
            metadata={"workspace": context.workspace.name},
        )


class BrokenTool(EchoTool):
    name = "broken"

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        raise RuntimeError("private diagnostic detail")


def make_call(name: str, arguments: dict[str, object] | None) -> ToolCall:
    return ToolCall(
        id="call-1",
        name=name,
        raw_arguments="{}",
        arguments=arguments,
        argument_error="invalid JSON" if arguments is None else None,
    )


def execute(registry: ToolRegistry, call: ToolCall, workspace: Path):
    context = ToolExecutionContext(
        session_id="session",
        workspace=workspace,
        cancellation_requested=lambda: False,
    )
    return asyncio.run(registry.execute(call, context))


def test_registry_exposes_openai_tool_schema_and_executes(tmp_path: Path) -> None:
    registry = ToolRegistry([EchoTool()])

    result = execute(registry, make_call("echo", {"text": "hello"}), tmp_path)

    assert result.status == "success"
    assert result.output == "hello"
    assert result.metadata["workspace"] == tmp_path.name
    assert registry.definitions[0]["function"]["name"] == "echo"


def test_unknown_invalid_and_extra_arguments_are_structured(tmp_path: Path) -> None:
    registry = ToolRegistry([EchoTool()])

    unknown = execute(registry, make_call("missing", {}), tmp_path)
    invalid_json = execute(registry, make_call("echo", None), tmp_path)
    invalid_schema = execute(registry, make_call("echo", {"text": "", "extra": 1}), tmp_path)

    assert unknown.error_type == "unknown_tool"
    assert invalid_json.error_type == "invalid_arguments"
    assert invalid_schema.error_type == "invalid_arguments"


def test_internal_exception_does_not_cross_registry_boundary(tmp_path: Path) -> None:
    result = execute(ToolRegistry([BrokenTool()]), make_call("broken", {"text": "x"}), tmp_path)

    assert result.status == "error"
    assert result.error_type == "internal_tool_error"
    assert "private diagnostic detail" not in result.output


def test_tool_context_and_result_are_immutable(tmp_path: Path) -> None:
    context = ToolContext("session", tmp_path, lambda: False)
    result = ToolResult.success("ok", metadata={"a": 1})

    assert context.workspace == tmp_path
    try:
        result.metadata["a"] = 2  # type: ignore[index]
    except TypeError:
        pass
    else:
        raise AssertionError("metadata should be immutable")
