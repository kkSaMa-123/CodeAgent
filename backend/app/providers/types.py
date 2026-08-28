"""与具体模型 SDK 无关的消息和工具调用类型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

MessageRole: TypeAlias = Literal["system", "user", "assistant", "tool"]
JsonObject: TypeAlias = dict[str, Any]
ToolDefinition: TypeAlias = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """模型请求的一次本地工具调用。"""

    id: str
    name: str
    raw_arguments: str
    arguments: JsonObject | None = None
    argument_error: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.arguments is not None and self.argument_error is None


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """一次模型调用的 Token 用量；厂商未提供时保持为零。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Agent 保存的统一会话消息。"""

    role: MessageRole
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    provider_fields: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def system(cls, content: str) -> ChatMessage:
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> ChatMessage:
        return cls(role="user", content=content)

    @classmethod
    def tool(cls, content: str, tool_call_id: str) -> ChatMessage:
        return cls(role="tool", content=content, tool_call_id=tool_call_id)


@dataclass(frozen=True, slots=True)
class AssistantTurn:
    """厂商响应经过适配后的统一 Assistant 回合。"""

    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str | None = None
    provider_fields: Mapping[str, Any] = field(default_factory=dict)

    def as_message(self) -> ChatMessage:
        """转为下一轮模型请求所需的 Assistant 消息。"""

        return ChatMessage(
            role="assistant",
            content=self.content,
            tool_calls=self.tool_calls,
            provider_fields=self.provider_fields,
        )
