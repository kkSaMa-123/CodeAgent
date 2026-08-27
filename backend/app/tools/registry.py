"""工具发现、参数校验与异常边界。"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from pydantic import ValidationError

from app.agent.tools import ToolExecutionContext, ToolExecutionResult
from app.providers.redaction import SecretRedactor
from app.providers.types import ToolCall, ToolDefinition
from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.paths import WorkspaceError, validate_workspace

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(
        self,
        tools: Iterable[Tool] = (),
        *,
        output_limit: int = 20_000,
        redactor: SecretRedactor | None = None,
    ) -> None:
        if output_limit <= 0:
            raise ValueError("output_limit must be positive")
        self._tools: dict[str, Tool] = {}
        self._output_limit = output_limit
        self._redactor = redactor or SecretRedactor()
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    @property
    def definitions(self) -> Sequence[ToolDefinition]:
        return tuple(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.arguments_model.model_json_schema(),
                },
            }
            for tool in self._tools.values()
        )

    async def execute(
        self,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult.error(
                "unknown_tool",
                f"未知工具: {call.name}",
            ).to_agent_result()
        if not call.is_valid:
            return ToolResult.error(
                "invalid_arguments",
                "工具参数不是有效 JSON 对象",
                metadata={"detail": call.argument_error or "arguments are missing"},
            ).to_agent_result()

        try:
            arguments = tool.arguments_model.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult.error(
                "invalid_arguments",
                "工具参数校验失败",
                metadata={"errors": exc.errors(include_input=False, include_url=False)},
            ).to_agent_result()

        try:
            workspace = validate_workspace(context.workspace)
            tool_context = ToolContext(
                session_id=context.session_id,
                workspace=workspace,
                cancellation_requested=context.cancellation_requested,
                output_limit=self._output_limit,
                tool_call_id=call.id,
                on_approval_requested=context.on_approval_requested,
                on_approval_resolved=context.on_approval_resolved,
            )
            result = await tool.execute(arguments, tool_context)
        except WorkspaceError as exc:
            return ToolResult.error(exc.code.value, str(exc)).to_agent_result()
        except Exception as exc:
            logger.error(
                "tool execution failed: %s",
                self._redactor.redact(str(exc)),
                extra={"tool_name": tool.name},
            )
            return ToolResult.error(
                "internal_tool_error",
                "工具内部错误，未执行后续操作",
            ).to_agent_result()
        agent_result = result.to_agent_result()
        return ToolExecutionResult(
            status=agent_result.status,
            output=self._redactor.redact(agent_result.output),
            summary=self._redactor.redact(agent_result.summary),
            error_type=agent_result.error_type,
            metadata=self._redactor.redact_value(agent_result.metadata),
            modified_files=agent_result.modified_files,
            workspace_changed=agent_result.workspace_changed,
        )
