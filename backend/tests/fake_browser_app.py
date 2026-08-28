"""仅供本地浏览器验收使用，不发送任何模型请求。"""

from __future__ import annotations

import json

from app.agent.runtime import AgentRuntime
from app.agent.state import RunState
from app.api import AppServices, create_app
from app.config import ModelConfigurationStatus
from app.providers.fake import FakeProvider
from app.providers.types import AssistantTurn, ToolCall
from app.tools.defaults import build_file_tool_registry


def ready() -> ModelConfigurationStatus:
    return ModelConfigurationStatus(ready=True, summary={"provider": "fake", "model": "browser-qa"})


def runtime_factory(state: RunState) -> AgentRuntime:
    target = state.workspace / "browser-demo.txt"
    content = (
        "第二轮：历史 Diff 仍应保持第一轮内容。\n"
        if target.exists()
        else "第一轮：CodeAgent 对话管理验收。\n"
    )
    call = ToolCall(
        id="write-browser-demo",
        name="write_file",
        raw_arguments=json.dumps(
            {"path": "browser-demo.txt", "content": content}, ensure_ascii=False
        ),
        arguments={"path": "browser-demo.txt", "content": content},
    )
    return AgentRuntime(
        FakeProvider(
            AssistantTurn(tool_calls=(call,)), AssistantTurn(content="本轮文件修改已完成。")
        ),
        build_file_tool_registry(),
        system_prompt="browser acceptance",
    )


app = create_app(AppServices(runtime_factory=runtime_factory, config_inspector=ready))
