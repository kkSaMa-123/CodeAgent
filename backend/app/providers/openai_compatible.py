"""OpenAI-compatible Chat Completions 模型适配器。"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import openai
from openai import AsyncOpenAI

from app.config import ModelSettings
from app.providers.errors import ProviderError, ProviderErrorKind, RetryEvent
from app.providers.redaction import SecretRedactor
from app.providers.types import AssistantTurn, ChatMessage, TokenUsage, ToolCall, ToolDefinition

RetryCallback = Callable[[RetryEvent], Awaitable[None] | None]
DeltaCallback = Callable[[str], Awaitable[None] | None]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(slots=True)
class _PartialToolCall:
    id: str = ""
    name: str = ""
    arguments: str = ""


class OpenAICompatibleProvider:
    """把兼容 Chat Completions 的响应转换为 CodeAgent 领域类型。"""

    def __init__(
        self,
        settings: ModelSettings,
        *,
        client: Any | None = None,
        on_retry: RetryCallback | None = None,
        on_reasoning_delta: DeltaCallback | None = None,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._client = client or AsyncOpenAI(
            api_key=settings.api_key.get_secret_value(),
            base_url=str(settings.base_url),
            timeout=settings.timeout_seconds,
            # 由本适配器统一决定重试，避免 SDK 隐式重试造成不可观察行为。
            max_retries=0,
        )
        self._on_retry = on_retry
        self._on_reasoning_delta = on_reasoning_delta
        self._sleeper = sleeper
        self._redactor = SecretRedactor((settings.api_key.get_secret_value(),))

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> AssistantTurn:
        request: dict[str, Any] = {
            "model": self._settings.model,
            "messages": [self._message_payload(message) for message in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            request["tools"] = [dict(tool) for tool in tools]
        if self._settings.extra_body:
            request["extra_body"] = self._settings.extra_body

        return await self._request_with_retries(request)

    async def _request_with_retries(self, request: dict[str, Any]) -> AssistantTurn:
        for attempt in range(self._settings.max_retries + 1):
            try:
                response = await self._client.chat.completions.create(**request)
                return await self._consume_stream(response)
            except Exception as exc:
                error = self._normalize_error(exc)
                if not error.retryable or attempt >= self._settings.max_retries:
                    raise error from None

                retry_number = attempt + 1
                delay = min(float(2 ** (retry_number - 1)), 8.0)
                if self._on_retry is not None:
                    notification = self._on_retry(
                        RetryEvent(
                            attempt=retry_number,
                            max_retries=self._settings.max_retries,
                            error_kind=error.kind,
                            delay_seconds=delay,
                        )
                    )
                    if inspect.isawaitable(notification):
                        await notification
                await self._sleeper(delay)
        raise AssertionError("retry loop exited unexpectedly")

    async def _consume_stream(self, response: Any) -> AssistantTurn:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        reasoning_displayed = 0
        reasoning_display_buffer = ""
        partial_calls: dict[int, _PartialToolCall] = {}
        finish_reason: str | None = None
        token_usage = TokenUsage()

        try:
            async for chunk in response:
                usage = self._field(chunk, "usage")
                if usage is not None:
                    token_usage = TokenUsage(
                        prompt_tokens=int(self._field(usage, "prompt_tokens", 0) or 0),
                        completion_tokens=int(
                            self._field(usage, "completion_tokens", 0) or 0
                        ),
                        total_tokens=int(self._field(usage, "total_tokens", 0) or 0),
                    )
                choices = self._field(chunk, "choices", ()) or ()
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = self._field(choice, "finish_reason") or finish_reason
                delta = self._field(choice, "delta")
                if delta is None:
                    continue

                content = self._field(delta, "content")
                if isinstance(content, str) and content:
                    content_parts.append(content)

                reasoning = self._field(delta, "reasoning_content")
                if isinstance(reasoning, str) and reasoning:
                    reasoning_parts.append(reasoning)
                    if reasoning_displayed < 12_000:
                        visible = reasoning[: 12_000 - reasoning_displayed]
                        reasoning_displayed += len(visible)
                        reasoning_display_buffer += visible
                        if len(reasoning_display_buffer) >= 80 or "\n" in visible:
                            await self._notify_reasoning(
                                self._redactor.redact(reasoning_display_buffer)
                            )
                            reasoning_display_buffer = ""

                for tool_delta in self._field(delta, "tool_calls", ()) or ():
                    index = int(self._field(tool_delta, "index", 0) or 0)
                    partial = partial_calls.setdefault(index, _PartialToolCall())
                    call_id = self._field(tool_delta, "id")
                    if isinstance(call_id, str) and call_id:
                        partial.id = call_id
                    function = self._field(tool_delta, "function")
                    if function is not None:
                        name = self._field(function, "name")
                        arguments = self._field(function, "arguments")
                        if isinstance(name, str) and name:
                            partial.name += name
                        if isinstance(arguments, str) and arguments:
                            partial.arguments += arguments
        except TypeError as exc:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE,
                "模型流式响应不可迭代",
                retryable=False,
            ) from exc

        if reasoning_display_buffer:
            await self._notify_reasoning(
                self._redactor.redact(reasoning_display_buffer)
            )

        tool_calls = tuple(
            self._parse_tool_call(
                SimpleNamespace(
                    id=partial.id,
                    function=SimpleNamespace(
                        name=partial.name,
                        arguments=partial.arguments,
                    ),
                )
            )
            for _, partial in sorted(partial_calls.items())
        )
        reasoning_content = "".join(reasoning_parts)
        provider_fields = (
            {"reasoning_content": reasoning_content} if reasoning_content else {}
        )
        return AssistantTurn(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            usage=token_usage,
            finish_reason=finish_reason,
            provider_fields=provider_fields,
        )

    async def _notify_reasoning(self, content: str) -> None:
        if not content or self._on_reasoning_delta is None:
            return
        notification = self._on_reasoning_delta(content)
        if inspect.isawaitable(notification):
            await notification

    @staticmethod
    def _field(value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, Mapping):
            return value.get(name, default)
        result = getattr(value, name, default)
        if result is not default:
            return result
        model_extra = getattr(value, "model_extra", None)
        if isinstance(model_extra, Mapping):
            return model_extra.get(name, default)
        return default

    def _message_payload(self, message: ChatMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "tool":
            payload["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": tool_call.raw_arguments,
                    },
                }
                for tool_call in message.tool_calls
            ]
        for key, value in message.provider_fields.items():
            if key not in payload and value is not None:
                payload[key] = value
        return payload

    def _parse_response(self, response: Any) -> AssistantTurn:
        try:
            choice = response.choices[0]
            message = choice.message
        except (AttributeError, IndexError, TypeError) as exc:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE,
                "模型响应缺少 choices[0].message",
                retryable=False,
            ) from exc

        tool_calls = tuple(self._parse_tool_call(call) for call in (message.tool_calls or ()))
        provider_fields: dict[str, Any] = {}
        reasoning_content = getattr(message, "reasoning_content", None)
        if reasoning_content is None:
            model_extra = getattr(message, "model_extra", None)
            if isinstance(model_extra, Mapping):
                reasoning_content = model_extra.get("reasoning_content")
        if reasoning_content is not None:
            provider_fields["reasoning_content"] = reasoning_content

        usage = getattr(response, "usage", None)
        token_usage = TokenUsage(
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        )
        return AssistantTurn(
            content=getattr(message, "content", None),
            tool_calls=tool_calls,
            usage=token_usage,
            finish_reason=getattr(choice, "finish_reason", None),
            provider_fields=provider_fields,
        )

    @staticmethod
    def _parse_tool_call(call: Any) -> ToolCall:
        call_id = str(getattr(call, "id", ""))
        function = getattr(call, "function", None)
        name = str(getattr(function, "name", ""))
        raw_arguments = str(getattr(function, "arguments", ""))
        try:
            arguments = json.loads(raw_arguments)
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            return ToolCall(
                id=call_id,
                name=name,
                raw_arguments=raw_arguments,
                argument_error=f"invalid tool arguments: {exc}",
            )
        return ToolCall(
            id=call_id,
            name=name,
            raw_arguments=raw_arguments,
            arguments=arguments,
        )

    def _normalize_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        message = self._redactor.redact(str(exc)) or type(exc).__name__
        status_code = getattr(exc, "status_code", None)

        if isinstance(exc, openai.AuthenticationError):
            return ProviderError(
                ProviderErrorKind.AUTHENTICATION,
                message,
                retryable=False,
                status_code=status_code,
            )
        if isinstance(exc, openai.RateLimitError):
            return ProviderError(
                ProviderErrorKind.RATE_LIMIT,
                message,
                retryable=True,
                status_code=status_code,
            )
        if isinstance(exc, openai.APITimeoutError):
            return ProviderError(ProviderErrorKind.TIMEOUT, message, retryable=True)
        if isinstance(exc, openai.APIConnectionError):
            return ProviderError(ProviderErrorKind.CONNECTION, message, retryable=True)
        if isinstance(exc, openai.BadRequestError):
            return ProviderError(
                ProviderErrorKind.INVALID_REQUEST,
                message,
                retryable=False,
                status_code=status_code,
            )
        if isinstance(exc, openai.APIStatusError) and status_code is not None:
            retryable = int(status_code) >= 500
            kind = ProviderErrorKind.UNAVAILABLE if retryable else ProviderErrorKind.INVALID_REQUEST
            return ProviderError(kind, message, retryable=retryable, status_code=int(status_code))
        return ProviderError(ProviderErrorKind.UNKNOWN, message, retryable=False)
