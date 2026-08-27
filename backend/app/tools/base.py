"""本地工具的领域协议。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from app.agent.tools import ToolExecutionResult


class ToolArguments(BaseModel):
    """所有工具参数默认拒绝未声明字段。"""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class ToolContext:
    session_id: str
    workspace: Path
    cancellation_requested: Callable[[], bool]
    output_limit: int = 20_000
    tool_call_id: str = ""
    on_approval_requested: Callable[[Any], Awaitable[None]] | None = None
    on_approval_resolved: Callable[[Any, bool], Awaitable[None]] | None = None

    def __post_init__(self) -> None:
        if self.output_limit <= 0:
            raise ValueError("output_limit must be positive")


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: Literal["success", "error"]
    summary: str
    output: str = ""
    error_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    modified_files: tuple[str, ...] = ()
    workspace_changed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def success(
        cls,
        summary: str,
        *,
        output: str = "",
        metadata: Mapping[str, Any] | None = None,
        modified_files: tuple[str, ...] = (),
        workspace_changed: bool = False,
    ) -> ToolResult:
        return cls(
            status="success",
            summary=summary,
            output=output,
            metadata=metadata or {},
            modified_files=modified_files,
            workspace_changed=workspace_changed,
        )

    @classmethod
    def error(
        cls,
        error_type: str,
        summary: str,
        *,
        output: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        return cls(
            status="error",
            error_type=error_type,
            summary=summary,
            output=output,
            metadata=metadata or {},
        )

    def to_agent_result(self) -> ToolExecutionResult:
        return ToolExecutionResult(
            status=self.status,
            output=self.output,
            summary=self.summary,
            error_type=self.error_type,
            metadata=self.metadata,
            modified_files=self.modified_files,
            workspace_changed=self.workspace_changed,
        )


class Tool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def arguments_model(self) -> type[ToolArguments]: ...

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult: ...
