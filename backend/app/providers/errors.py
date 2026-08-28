"""模型厂商错误的归一化类型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProviderErrorKind(StrEnum):
    AUTHENTICATION = "authentication_error"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "request_timeout"
    CONNECTION = "connection_error"
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "provider_unavailable"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "provider_error"


class ProviderError(RuntimeError):
    """可安全返回给上层的标准化厂商错误。"""

    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class RetryEvent:
    """供后续事件总线转发的安全重试信息。"""

    attempt: int
    max_retries: int
    error_kind: ProviderErrorKind
    delay_seconds: float
