"""为 Agent 运行时测试提供可编排的模型 Provider。"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from app.providers.types import AssistantTurn, ChatMessage, ToolDefinition


class FakeProvider:
    """按顺序返回预置回合或抛出预置异常。"""

    def __init__(self, *responses: AssistantTurn | Exception) -> None:
        self._responses = deque(responses)
        self.calls: list[tuple[tuple[ChatMessage, ...], tuple[ToolDefinition, ...]]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> AssistantTurn:
        self.calls.append((tuple(messages), tuple(tools)))
        if not self._responses:
            raise AssertionError("FakeProvider has no response left")
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def remaining(self) -> int:
        return len(self._responses)

