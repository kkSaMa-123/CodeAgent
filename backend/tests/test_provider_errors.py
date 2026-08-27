from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import openai
import pytest

from app.config import ModelSettings
from app.providers import OpenAICompatibleProvider, ProviderError, ProviderErrorKind
from app.providers.redaction import REDACTED, SecretRedactor


def make_settings(monkeypatch: pytest.MonkeyPatch, *, max_retries: int = 2) -> ModelSettings:
    values = {
        "LLM_PROVIDER": "test-provider",
        "LLM_BASE_URL": "https://provider.example.com/v1",
        "LLM_API_KEY": "super-secret-provider-key",
        "LLM_MODEL": "test-model",
        "LLM_TIMEOUT_SECONDS": "30",
        "LLM_MAX_RETRIES": str(max_retries),
        "LLM_EXTRA_BODY_JSON": "{}",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return ModelSettings(_env_file=None)


def make_response(content: str = "done") -> SimpleNamespace:
    message = SimpleNamespace(
        content=content,
        tool_calls=[],
        reasoning_content=None,
        model_extra=None,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=None,
    )


def make_client(*side_effects: object) -> tuple[SimpleNamespace, AsyncMock]:
    create = AsyncMock(side_effect=list(side_effects))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, create


def make_status_error(error_type: type[openai.APIStatusError], status: int, message: str):
    request = httpx2.Request("POST", "https://provider.example.com/chat/completions")
    response = httpx2.Response(status, request=request)
    return error_type(message, response=response, body=None)


def test_rate_limit_retries_with_bounded_backoff_and_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(monkeypatch, max_retries=2)
    rate_limit = make_status_error(openai.RateLimitError, 429, "rate limited")
    client, create = make_client(rate_limit, rate_limit, make_response())
    retry_events = []
    sleeper = AsyncMock()
    provider = OpenAICompatibleProvider(
        settings,
        client=client,
        on_retry=retry_events.append,
        sleeper=sleeper,
    )

    turn = asyncio.run(provider.complete([]))

    assert turn.content == "done"
    assert create.await_count == 3
    assert [event.attempt for event in retry_events] == [1, 2]
    assert [event.error_kind for event in retry_events] == [
        ProviderErrorKind.RATE_LIMIT,
        ProviderErrorKind.RATE_LIMIT,
    ]
    assert [call.args[0] for call in sleeper.await_args_list] == [1.0, 2.0]


def test_authentication_failure_is_not_retried_or_leaked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(monkeypatch, max_retries=3)
    auth_error = make_status_error(
        openai.AuthenticationError,
        401,
        "invalid api_key=super-secret-provider-key",
    )
    client, create = make_client(auth_error)
    sleeper = AsyncMock()
    provider = OpenAICompatibleProvider(settings, client=client, sleeper=sleeper)

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.complete([]))

    assert caught.value.kind is ProviderErrorKind.AUTHENTICATION
    assert caught.value.retryable is False
    assert create.await_count == 1
    assert sleeper.await_count == 0
    assert "super-secret-provider-key" not in str(caught.value)
    assert REDACTED in str(caught.value)


def test_timeout_retries_only_up_to_configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(monkeypatch, max_retries=1)
    request = httpx2.Request("POST", "https://provider.example.com/chat/completions")
    timeout_error = openai.APITimeoutError(request=request)
    client, create = make_client(timeout_error, timeout_error)
    provider = OpenAICompatibleProvider(settings, client=client, sleeper=AsyncMock())

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.complete([]))

    assert caught.value.kind is ProviderErrorKind.TIMEOUT
    assert create.await_count == 2


def test_bad_request_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(monkeypatch, max_retries=3)
    bad_request = make_status_error(openai.BadRequestError, 400, "unknown model")
    client, create = make_client(bad_request)
    provider = OpenAICompatibleProvider(settings, client=client, sleeper=AsyncMock())

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.complete([]))

    assert caught.value.kind is ProviderErrorKind.INVALID_REQUEST
    assert caught.value.retryable is False
    assert create.await_count == 1


def test_redactor_removes_known_secret_and_authorization_headers() -> None:
    redactor = SecretRedactor(("known-secret",))
    text = "known-secret Authorization: Bearer bearer-value token=another-value"

    sanitized = redactor.redact(text)

    assert "known-secret" not in sanitized
    assert "bearer-value" not in sanitized
    assert "another-value" not in sanitized
    assert sanitized.count(REDACTED) == 3

