"""在模型错误跨越 Provider 边界前清理敏感信息。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

REDACTED = "[REDACTED]"


class SecretRedactor:
    """清理已知密钥以及常见 Authorization/API Key 表达。"""

    _authorization = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+")
    _api_key = re.compile(r"(?i)((?:api[_-]?key|token)\s*[=:]\s*)[^\s,;]+")
    _common_key = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets = tuple(
            sorted((secret for secret in secrets if secret), key=len, reverse=True)
        )

    def redact(self, text: str) -> str:
        sanitized = text
        for secret in self._secrets:
            sanitized = sanitized.replace(secret, REDACTED)
        sanitized = self._authorization.sub(rf"\1{REDACTED}", sanitized)
        sanitized = self._api_key.sub(rf"\1{REDACTED}", sanitized)
        return self._common_key.sub(REDACTED, sanitized)

    def redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, Mapping):
            return {str(key): self.redact_value(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return tuple(self.redact_value(item) for item in value)
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        return value
