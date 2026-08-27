"""Agent 循环与具体工具注册表之间的最小协议。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol

from app.providers.types import ToolCall, ToolDefinition


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    session_id: str
    workspace: Path
    cancellation_requested: Callable[[], bool]
    on_approval_requested: Callable[[Any], Awaitable[None]] | None = None
    on_approval_resolved: Callable[[Any, bool], Awaitable[None]] | None = None


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    status: Literal["success", "error"]
    output: str
    summary: str
    error_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    modified_files: tuple[str, ...] = ()
    workspace_changed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def success(
        cls,
        output: str,
        *,
        summary: str = "工具执行成功",
        modified_files: Sequence[str] = (),
        workspace_changed: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> ToolExecutionResult:
        return cls(
            status="success",
            output=output,
            summary=summary,
            metadata=metadata or {},
            modified_files=tuple(modified_files),
            workspace_changed=workspace_changed,
        )

    @classmethod
    def error(
        cls,
        output: str,
        *,
        error_type: str,
        summary: str = "工具执行失败",
        metadata: Mapping[str, Any] | None = None,
    ) -> ToolExecutionResult:
        return cls(
            status="error",
            output=output,
            summary=summary,
            error_type=error_type,
            metadata=metadata or {},
        )

    def to_message_content(self) -> str:
        payload: dict[str, Any] = {
            "status": self.status,
            "summary": self.summary,
            "output": self.output,
        }
        if self.error_type is not None:
            payload["error_type"] = self.error_type
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        if self.modified_files:
            payload["modified_files"] = list(self.modified_files)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class ToolExecutor(Protocol):
    @property
    def definitions(self) -> Sequence[ToolDefinition]: ...

    async def execute(
        self,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult: ...


class MappingToolExecutor:
    """面向测试和轻量组装的函数工具执行器。"""

    def __init__(
        self,
        handlers: Mapping[
            str,
            Callable[[ToolCall, ToolExecutionContext], ToolExecutionResult],
        ],
        definitions: Sequence[ToolDefinition] = (),
    ) -> None:
        self._handlers = dict(handlers)
        self._definitions = tuple(definitions)

    @property
    def definitions(self) -> Sequence[ToolDefinition]:
        return self._definitions

    async def execute(
        self,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        handler = self._handlers.get(call.name)
        if handler is None:
            return ToolExecutionResult.error(
                f"未知工具: {call.name}",
                error_type="unknown_tool",
            )
        return handler(call, context)
