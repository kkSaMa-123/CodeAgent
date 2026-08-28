from __future__ import annotations

import asyncio
from collections.abc import Sequence

from app.providers import (
    AssistantTurn,
    ChatMessage,
    ModelProvider,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)


class FakeProvider:
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> AssistantTurn:
        del messages, tools
        return AssistantTurn(content="fake response")


def test_tool_call_distinguishes_valid_and_invalid_arguments() -> None:
    valid = ToolCall(
        id="call-1",
        name="read_file",
        raw_arguments='{"path":"main.py"}',
        arguments={"path": "main.py"},
    )
    invalid = ToolCall(
        id="call-2",
        name="read_file",
        raw_arguments="not-json",
        argument_error="invalid JSON",
    )

    assert valid.is_valid is True
    assert invalid.is_valid is False


def test_assistant_turn_preserves_tool_calls_usage_and_provider_fields() -> None:
    tool_call = ToolCall(
        id="call-1",
        name="read_file",
        raw_arguments="{}",
        arguments={},
    )
    turn = AssistantTurn(
        tool_calls=(tool_call,),
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="tool_calls",
        provider_fields={"reasoning_content": "private"},
    )

    message = turn.as_message()

    assert message.role == "assistant"
    assert message.tool_calls == (tool_call,)
    assert message.provider_fields["reasoning_content"] == "private"
    assert turn.usage.total_tokens == 15


def test_fake_provider_satisfies_runtime_protocol() -> None:
    provider = FakeProvider()

    result = asyncio.run(provider.complete([ChatMessage.user("hello")]))

    assert isinstance(provider, ModelProvider)
    assert result.content == "fake response"
