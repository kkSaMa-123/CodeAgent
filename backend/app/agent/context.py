"""有界上下文与工具输出管理。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.providers.types import ChatMessage


def truncate_text(text: str, max_chars: int) -> str:
    """超限时保留头尾，并嵌入可机器测试的长度标记。"""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(text) <= max_chars:
        return text

    marker_template = "\n... [已截断：原始长度 {original} 字符，省略 {omitted} 字符] ...\n"
    marker = marker_template.format(original=len(text), omitted=len(text))
    if len(marker) >= max_chars:
        return marker[:max_chars]

    retained = max_chars - len(marker)
    head_length = (retained + 1) // 2
    tail_length = retained - head_length
    omitted = len(text) - retained
    marker = marker_template.format(original=len(text), omitted=omitted)

    # 数字位数变化可能改变 marker 长度，再计算一次可用空间。
    retained = max_chars - len(marker)
    head_length = (retained + 1) // 2
    tail_length = retained - head_length
    tail = text[-tail_length:] if tail_length else ""
    return text[:head_length] + marker + tail


def estimate_message_chars(message: ChatMessage) -> int:
    size = len(message.role) + len(message.content or "")
    size += len(message.tool_call_id or "")
    for call in message.tool_calls:
        size += len(call.id) + len(call.name) + len(call.raw_arguments)
    return size


def estimate_context_chars(messages: Sequence[ChatMessage]) -> int:
    return sum(estimate_message_chars(message) for message in messages)


@dataclass(frozen=True, slots=True)
class ContextWindow:
    budget_chars: int = 120_000

    def __post_init__(self) -> None:
        if self.budget_chars <= 0:
            raise ValueError("budget_chars must be positive")

    def prepare(self, messages: Sequence[ChatMessage]) -> tuple[ChatMessage, ...]:
        """按不可拆分的工具交互组删除最旧历史。"""

        groups = self._group_messages(messages)
        if not groups:
            return ()

        essential = self._essential_groups(groups)
        selected = list(range(len(groups)))
        for index in tuple(selected):
            flattened = self._flatten(groups, selected)
            if estimate_context_chars(flattened) <= self.budget_chars:
                break
            if index not in essential:
                selected.remove(index)
        return self._flatten(groups, selected)

    @staticmethod
    def _group_messages(messages: Sequence[ChatMessage]) -> list[tuple[ChatMessage, ...]]:
        groups: list[tuple[ChatMessage, ...]] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role == "assistant" and message.tool_calls:
                call_ids = {call.id for call in message.tool_calls}
                group = [message]
                cursor = index + 1
                while cursor < len(messages):
                    following = messages[cursor]
                    if following.role != "tool" or following.tool_call_id not in call_ids:
                        break
                    group.append(following)
                    cursor += 1
                groups.append(tuple(group))
                index = cursor
                continue
            groups.append((message,))
            index += 1
        return groups

    @staticmethod
    def _essential_groups(groups: Sequence[tuple[ChatMessage, ...]]) -> set[int]:
        essential: set[int] = set()
        found_system = False
        found_user = False
        for index, group in enumerate(groups):
            for message in group:
                if message.role == "system" and not found_system:
                    essential.add(index)
                    found_system = True
                if message.role == "user" and not found_user:
                    essential.add(index)
                    found_user = True
        # 最近交互（包括尚未收齐 observation 的调用）必须保留。
        essential.add(len(groups) - 1)
        return essential

    @staticmethod
    def _flatten(
        groups: Sequence[tuple[ChatMessage, ...]],
        indexes: Sequence[int],
    ) -> tuple[ChatMessage, ...]:
        return tuple(message for index in indexes for message in groups[index])


@dataclass(frozen=True, slots=True)
class ConversationContext:
    """从持久化语义消息生成首目标、旧摘要和最近轮次。"""

    budget_chars: int = 60_000

    def build(self, history: Sequence[dict[str, str]]) -> tuple[ChatMessage, ...]:
        semantic = []
        for item in history:
            if item.get("role") == "user":
                semantic.append(ChatMessage.user(item["content"]))
            elif item.get("role") == "assistant":
                semantic.append(ChatMessage(role="assistant", content=item["content"]))
        if estimate_context_chars(semantic) <= self.budget_chars:
            return tuple(semantic)
        if not semantic:
            return ()
        first_user = next((message for message in semantic if message.role == "user"), semantic[0])
        recent: list[ChatMessage] = []
        used = estimate_message_chars(first_user)
        recent_budget = max(1, int(self.budget_chars * 0.65))
        for message in reversed(semantic):
            size = estimate_message_chars(message)
            if used + size > recent_budget:
                break
            recent.append(message)
            used += size
        recent.reverse()
        recent_ids = {id(message) for message in recent}
        older = [
            message
            for message in semantic
            if message is not first_user and id(message) not in recent_ids
        ]
        summary_lines = [
            f"- {message.role}: {truncate_text(message.content or '', 240)}" for message in older
        ]
        summary = truncate_text(
            "较早对话摘要：\n" + "\n".join(summary_lines), max(1, self.budget_chars - used)
        )
        result = [first_user]
        if older:
            result.append(ChatMessage.system(summary))
        result.extend(message for message in recent if message is not first_user)
        return tuple(result)
