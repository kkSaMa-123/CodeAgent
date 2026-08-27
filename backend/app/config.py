"""从环境变量读取并校验 CodeAgent 模型配置。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class ModelSettings(BaseSettings):
    """模型服务配置。

    提供商、地址、密钥和模型必须由环境变量或未入库的 ``.env`` 提供。
    类中不保存任何厂商默认值，避免切换提供商时修改源码。
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    provider: str = Field(validation_alias="LLM_PROVIDER", min_length=1)
    base_url: AnyHttpUrl = Field(validation_alias="LLM_BASE_URL")
    api_key: SecretStr = Field(validation_alias="LLM_API_KEY", min_length=1)
    model: str = Field(validation_alias="LLM_MODEL", min_length=1)
    timeout_seconds: float = Field(
        default=60.0,
        validation_alias="LLM_TIMEOUT_SECONDS",
        gt=0,
        le=600,
    )
    max_retries: int = Field(
        default=2,
        validation_alias="LLM_MAX_RETRIES",
        ge=0,
        le=10,
    )
    extra_body: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="LLM_EXTRA_BODY_JSON",
    )

    @field_validator("provider", "model", mode="before")
    @classmethod
    def reject_blank_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def reject_blank_api_key(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    def safe_summary(self) -> dict[str, str | bool]:
        """返回可向前端或日志公开的非敏感配置摘要。"""

        return {
            "provider": self.provider,
            "base_url": str(self.base_url),
            "model": self.model,
            "api_key_configured": bool(self.api_key.get_secret_value()),
        }


@dataclass(frozen=True, slots=True)
class ModelConfigurationStatus:
    """不包含凭据的配置就绪状态。"""

    ready: bool
    summary: dict[str, str | bool] | None = None
    errors: tuple[str, ...] = ()


def load_model_settings(*, env_file: Path | None = ENV_FILE) -> ModelSettings:
    """加载严格模型配置；Agent 启动任务前必须调用此函数。"""

    # pydantic-settings 在运行时从环境变量提供必填字段，mypy 无法推断该动态来源。
    return ModelSettings(_env_file=env_file)  # type: ignore[call-arg]


def inspect_model_configuration(*, env_file: Path | None = ENV_FILE) -> ModelConfigurationStatus:
    """检查配置但不阻止 Web 后端启动，也不暴露字段输入值。"""

    try:
        settings = load_model_settings(env_file=env_file)
    except ValidationError as exc:
        fields = tuple(
            str(error.get("loc", ("unknown",))[0])
            for error in exc.errors(include_input=False, include_url=False)
        )
        return ModelConfigurationStatus(ready=False, errors=fields)
    return ModelConfigurationStatus(ready=True, summary=settings.safe_summary())
