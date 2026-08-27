"""DeepSeek 真实 Tool Calling 冒烟测试。

默认测试套件不会联网。只有用户在本地环境显式设置
``RUN_LIVE_LLM_TESTS=1`` 且提供完整 LLM 环境变量时才会运行。
"""

from __future__ import annotations

import asyncio
import os

import pytest

from app.config import load_model_settings
from app.providers import ChatMessage, OpenAICompatibleProvider

pytestmark = pytest.mark.live


def test_real_deepseek_tool_call_round_trip() -> None:
    if os.environ.get("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("设置 RUN_LIVE_LLM_TESTS=1 才会调用真实模型 API")

    settings = load_model_settings()
    provider = OpenAICompatibleProvider(settings)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_test_value",
                "description": "返回冒烟测试使用的固定值",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
    ]
    messages = [
        ChatMessage.system(
            "你正在执行 API 冒烟测试。必须先且只调用一次 get_test_value，"
            "收到工具结果后用一句话回答结果。"
        ),
        ChatMessage.user("请完成工具调用测试。"),
    ]

    first_turn = asyncio.run(provider.complete(messages, tools))

    assert len(first_turn.tool_calls) == 1
    tool_call = first_turn.tool_calls[0]
    assert tool_call.name == "get_test_value"
    assert tool_call.is_valid

    messages.extend(
        [
            first_turn.as_message(),
            ChatMessage.tool('{"status":"success","value":"tool-call-ok"}', tool_call.id),
        ]
    )
    final_turn = asyncio.run(provider.complete(messages, tools))

    assert final_turn.content
    assert "tool-call-ok" in final_turn.content
