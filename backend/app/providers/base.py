"""Agent 运行时依赖的最小模型 Provider 协议。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.providers.types import AssistantTurn, ChatMessage, ToolDefinition


@runtime_checkable
class ModelProvider(Protocol):
    """所有模型厂商适配器必须满足的异步接口。"""

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> AssistantTurn:
        """根据上下文返回一次标准化 Assistant 响应。"""
        ...

