"""阶段四默认文件工具集。"""

from __future__ import annotations

from app.capabilities import ALL_TOOL_NAMES, validate_tool_names
from app.providers.redaction import SecretRedactor
from app.safety.approval import ApprovalService
from app.tools.base import Tool
from app.tools.command import RunCommandTool
from app.tools.discovery import ListFilesTool
from app.tools.editing import ReplaceInFileTool, WriteFileTool
from app.tools.git_tools import GitDiffTool
from app.tools.reading import ReadFileTool, SearchTextTool
from app.tools.registry import ToolRegistry


def build_file_tool_registry(
    *,
    output_limit: int = 20_000,
    approval_service: ApprovalService | None = None,
    redactor: SecretRedactor | None = None,
    enabled_tools: tuple[str, ...] | list[str] | None = None,
) -> ToolRegistry:
    enabled = set(
        validate_tool_names(enabled_tools if enabled_tools is not None else list(ALL_TOOL_NAMES))
    )
    tools: list[Tool] = [
        ListFilesTool(),
        ReadFileTool(),
        SearchTextTool(),
        WriteFileTool(),
        ReplaceInFileTool(),
        GitDiffTool(),
        RunCommandTool(approval_service),
    ]
    return ToolRegistry(
        [tool for tool in tools if tool.name in enabled],
        output_limit=output_limit,
        redactor=redactor,
    )
