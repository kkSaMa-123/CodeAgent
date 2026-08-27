from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsError

from app.config import ModelSettings, inspect_model_configuration

MODEL_ENV_KEYS = (
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
    "LLM_EXTRA_BODY_JSON",
)


@pytest.fixture(autouse=True)
def isolated_model_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in MODEL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def set_valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "LLM_PROVIDER": "deepseek",
        "LLM_BASE_URL": "https://api.deepseek.com",
        "LLM_API_KEY": "test-secret-not-real",
        "LLM_MODEL": "test-model",
        "LLM_TIMEOUT_SECONDS": "45",
        "LLM_MAX_RETRIES": "3",
        "LLM_EXTRA_BODY_JSON": '{"thinking":{"type":"disabled"}}',
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_loads_complete_deepseek_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_environment(monkeypatch)

    settings = ModelSettings(_env_file=None)

    assert settings.provider == "deepseek"
    assert str(settings.base_url) == "https://api.deepseek.com/"
    assert settings.api_key.get_secret_value() == "test-secret-not-real"
    assert settings.timeout_seconds == 45
    assert settings.max_retries == 3
    assert settings.extra_body == {"thinking": {"type": "disabled"}}
    assert "test-secret-not-real" not in repr(settings)


def test_switches_provider_using_environment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "compatible-gateway")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "gateway-model")

    settings = ModelSettings(_env_file=None)

    assert settings.provider == "compatible-gateway"
    assert str(settings.base_url) == "https://gateway.example.com/v1"
    assert settings.model == "gateway-model"


@pytest.mark.parametrize(
    "missing_key",
    ["LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"],
)
def test_rejects_missing_required_environment(
    monkeypatch: pytest.MonkeyPatch,
    missing_key: str,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.delenv(missing_key)

    with pytest.raises(ValidationError):
        ModelSettings(_env_file=None)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("LLM_BASE_URL", "not-a-url"),
        ("LLM_TIMEOUT_SECONDS", "0"),
        ("LLM_TIMEOUT_SECONDS", "not-a-number"),
        ("LLM_MAX_RETRIES", "-1"),
        ("LLM_MAX_RETRIES", "100"),
    ],
)
def test_rejects_invalid_environment_values(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: str,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError):
        ModelSettings(_env_file=None)


def test_rejects_invalid_extra_body_json(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("LLM_EXTRA_BODY_JSON", "not-json")

    with pytest.raises(SettingsError):
        ModelSettings(_env_file=None)


def test_configuration_status_never_exposes_key(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_environment(monkeypatch)

    status = inspect_model_configuration()

    assert status.ready is True
    assert status.summary is not None
    assert status.summary["api_key_configured"] is True
    assert "test-secret-not-real" not in repr(status)


def test_configuration_status_reports_missing_fields_without_values() -> None:
    status = inspect_model_configuration(env_file=None)

    assert status.ready is False
    assert set(status.errors) >= {"LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"}
