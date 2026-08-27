"""无进展工具重复调用检测。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.providers.types import ToolCall


class RepetitionDecision(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    STOP = "stop"


def tool_call_signature(call: ToolCall, workspace_version: int) -> str:
    """使等价 JSON 参数具有同一签名，工作区变化则签名变化。"""

    arguments: Any
    if call.arguments is not None:
        arguments = call.arguments
    else:
        try:
            arguments = json.loads(call.raw_arguments)
        except json.JSONDecodeError:
            arguments = call.raw_arguments.strip()
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{call.name.strip().lower()}|{canonical}|workspace:{workspace_version}"


@dataclass(slots=True)
class RepetitionGuard:
    warning_threshold: int = 3
    stop_threshold: int = 5
    _last_signature: str | None = None
    _consecutive_count: int = 0

    def __post_init__(self) -> None:
        if self.warning_threshold < 2:
            raise ValueError("warning_threshold must be at least 2")
        if self.stop_threshold <= self.warning_threshold:
            raise ValueError("stop_threshold must be greater than warning_threshold")

    @property
    def consecutive_count(self) -> int:
        return self._consecutive_count

    def check(self, call: ToolCall, workspace_version: int) -> RepetitionDecision:
        signature = tool_call_signature(call, workspace_version)
        if signature == self._last_signature:
            self._consecutive_count += 1
        else:
            self._last_signature = signature
            self._consecutive_count = 1

        if self._consecutive_count >= self.stop_threshold:
            return RepetitionDecision.STOP
        if self._consecutive_count >= self.warning_threshold:
            return RepetitionDecision.WARN
        return RepetitionDecision.ALLOW

