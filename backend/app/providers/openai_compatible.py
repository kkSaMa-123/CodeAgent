"""OpenAI-compatible Chat Completions 模型适配器。"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import openai
from openai import AsyncOpenAI

from app.config import ModelSettings
from app.providers.errors import ProviderError, ProviderErrorKind, RetryEvent
from app.providers.redaction import SecretRedactor
from app.providers.types import AssistantTurn, ChatMessage, TokenUsage, ToolCall, ToolDefinition

RetryCallback = Callable[[RetryEvent], Awaitable[None] | None]
Sleeper = Callable[[float], Awaitable[None]]


class OpenAICompatibleProvider:
    """把兼容 Chat Completions 的响应转换为 CodeAgent 领域类型。"""

    def __init__(
        self,
        settings: ModelSettings,
        *,
        client: Any | None = None,
        on_retry: RetryCallback | None = None,
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
            "stream": False,
        }
        if tools:
            request["tools"] = [dict(tool) for tool in tools]
        if self._settings.extra_body:
            request["extra_body"] = self._settings.extra_body

        response = await self._request_with_retries(request)
        return self._parse_response(response)

    async def _request_with_retries(self, request: dict[str, Any]) -> Any:
        for attempt in range(self._settings.max_retries + 1):
            try:
                return await self._client.chat.completions.create(**request)
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

