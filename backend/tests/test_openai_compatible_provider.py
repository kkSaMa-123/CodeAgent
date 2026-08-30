from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import ModelSettings
from app.providers import ChatMessage, OpenAICompatibleProvider


class AsyncStream:
    def __init__(self, *chunks: object) -> None:
        self._chunks = chunks

    def __aiter__(self):
        self._iterator = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> ModelSettings:
    values = {
        "LLM_PROVIDER": "test-provider",
        "LLM_BASE_URL": "https://provider.example.com/v1",
        "LLM_API_KEY": "provider-test-secret",
        "LLM_MODEL": "test-model",
        "LLM_TIMEOUT_SECONDS": "30",
        "LLM_MAX_RETRIES": "0",
        "LLM_EXTRA_BODY_JSON": "{}",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return ModelSettings(_env_file=None)


def make_tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def make_response(
    *,
    content: str | None = None,
    tool_calls: list[SimpleNamespace] | None = None,
    reasoning_content: str | None = None,
) -> AsyncStream:
    deltas = [
        SimpleNamespace(index=index, id=call.id, function=call.function)
        for index, call in enumerate(tool_calls or [])
    ]
    delta = SimpleNamespace(
        content=content,
        tool_calls=deltas,
        reasoning_content=reasoning_content,
        model_extra=None,
    )
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=delta,
                finish_reason="tool_calls" if tool_calls else "stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=7, total_tokens=19),
    )
    return AsyncStream(chunk)


def make_client(*responses: object) -> tuple[SimpleNamespace, AsyncMock]:
    create = AsyncMock(side_effect=list(responses))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, create


def test_parses_standard_tool_call_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(monkeypatch)
    response = make_response(
        tool_calls=[make_tool_call("call-1", "read_file", '{"path":"main.py"}')]
    )
    client, create = make_client(response)
    provider = OpenAICompatibleProvider(settings, client=client)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    turn = asyncio.run(provider.complete([ChatMessage.user("read main.py")], tools))

    assert turn.tool_calls[0].id == "call-1"
    assert turn.tool_calls[0].arguments == {"path": "main.py"}
    assert turn.usage.total_tokens == 19
    request = create.await_args.kwargs
    assert request["model"] == "test-model"
    assert request["stream"] is True
    assert request["tools"] == tools
    assert request["messages"] == [{"role": "user", "content": "read main.py"}]


def test_preserves_multiple_tool_calls_in_response_order(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(monkeypatch)
    response = make_response(
        tool_calls=[
            make_tool_call("call-1", "read_file", '{"path":"a.py"}'),
            make_tool_call("call-2", "read_file", '{"path":"b.py"}'),
        ]
    )
    client, _ = make_client(response)
    provider = OpenAICompatibleProvider(settings, client=client)

    turn = asyncio.run(provider.complete([ChatMessage.user("read files")]))

    assert [call.id for call in turn.tool_calls] == ["call-1", "call-2"]


def test_reassembles_streamed_reasoning_content_and_tool_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(monkeypatch)
    chunks = AsyncStream(
        SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    reasoning_content="先读取",
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id="call-1",
                            function=SimpleNamespace(
                                name="read_file", arguments='{"path"'
                            ),
                        )
                    ],
                ),
                finish_reason=None,
            )],
            usage=None,
        ),
        SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    reasoning_content="文件。",
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id=None,
                            function=SimpleNamespace(
                                name=None, arguments=':"main.py"}'
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )],
            usage=None,
        ),
        SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        ),
    )
    client, _ = make_client(chunks)
    deltas = []
    provider = OpenAICompatibleProvider(
        settings, client=client, on_reasoning_delta=deltas.append
    )

    turn = asyncio.run(provider.complete([ChatMessage.user("读取")]))

    assert turn.provider_fields["reasoning_content"] == "先读取文件。"
    assert deltas == ["先读取文件。"]
    assert turn.tool_calls[0].name == "read_file"
    assert turn.tool_calls[0].arguments == {"path": "main.py"}
    assert turn.usage.total_tokens == 14


@pytest.mark.parametrize("raw_arguments", ["not-json", "[]", "null"])
def test_invalid_tool_arguments_are_recoverable(
    monkeypatch: pytest.MonkeyPatch,
    raw_arguments: str,
) -> None:
    settings = make_settings(monkeypatch)
    response = make_response(tool_calls=[make_tool_call("call-1", "read_file", raw_arguments)])
    client, _ = make_client(response)
    provider = OpenAICompatibleProvider(settings, client=client)

    turn = asyncio.run(provider.complete([ChatMessage.user("read")]))

    assert turn.tool_calls[0].is_valid is False
    assert turn.tool_calls[0].arguments is None
    assert "invalid tool arguments" in (turn.tool_calls[0].argument_error or "")


def test_reasoning_content_is_returned_to_provider_but_not_normal_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(monkeypatch)
    first = make_response(
        tool_calls=[make_tool_call("call-1", "read_file", '{"path":"main.py"}')],
        reasoning_content="private reasoning",
    )
    second = make_response(content="done")
    client, create = make_client(first, second)
    reasoning_deltas = []
    provider = OpenAICompatibleProvider(
        settings, client=client, on_reasoning_delta=reasoning_deltas.append
    )

    first_turn = asyncio.run(provider.complete([ChatMessage.user("read")]))
    messages = [
        ChatMessage.user("read"),
        first_turn.as_message(),
        ChatMessage.tool('{"status":"success"}', "call-1"),
    ]
    second_turn = asyncio.run(provider.complete(messages))

    assert first_turn.content is None
    assert first_turn.provider_fields == {"reasoning_content": "private reasoning"}
    assert reasoning_deltas == ["private reasoning"]
    assert second_turn.content == "done"
    second_request_messages = create.await_args_list[1].kwargs["messages"]
    assert second_request_messages[1]["reasoning_content"] == "private reasoning"
    assert second_request_messages[2]["tool_call_id"] == "call-1"


def test_passes_provider_extra_body_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(
        monkeypatch,
        LLM_EXTRA_BODY_JSON='{"thinking":{"type":"enabled"}}',
    )
    client, create = make_client(make_response(content="done"))
    provider = OpenAICompatibleProvider(settings, client=client)

    asyncio.run(provider.complete([ChatMessage.user("hello")]))

    assert create.await_args.kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
