"""原子文件写入与确定性局部替换。"""

from __future__ import annotations

import difflib
import os
import tempfile
from pathlib import Path

from pydantic import Field

from app.tools.base import ToolArguments, ToolContext, ToolResult
from app.tools.paths import resolve_workspace_path
from app.tools.reading import UnsupportedTextFile, read_utf8_text


def unified_text_diff(relative_path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
        )
    )


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class WriteFileArguments(ToolArguments):
    path: str
    content: str


class WriteFileTool:
    name = "write_file"
    description = "在工作区内原子创建或覆盖 UTF-8 文本文件，返回 unified diff。"
    arguments_model = WriteFileArguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        parsed = WriteFileArguments.model_validate(arguments)
        path = resolve_workspace_path(context.workspace, parsed.path, must_exist=False)
        if path.exists() and not path.is_file():
            return ToolResult.error("not_a_file", "写入目标不是普通文件")
        created = not path.exists()
        before = ""
        if not created:
            try:
                before = read_utf8_text(path)
            except UnsupportedTextFile as exc:
                return ToolResult.error("unsupported_file", str(exc))
        relative = path.relative_to(context.workspace).as_posix()
        diff = unified_text_diff(relative, before, parsed.content)
        atomic_write_text(path, parsed.content)
        action = "新建" if created else "更新"
        return ToolResult.success(
            f"{action}文件 {relative}",
            output=diff,
            metadata={"path": relative, "created": created, "diff": diff},
            modified_files=(relative,),
            workspace_changed=before != parsed.content,
        )


class ReplaceInFileArguments(ToolArguments):
    path: str
    old_text: str = Field(min_length=1)
    new_text: str
    replace_all: bool = False


class ReplaceInFileTool:
    name = "replace_in_file"
    description = "精确替换文件中唯一旧文本；多处替换需要显式启用 replace_all。"
    arguments_model = ReplaceInFileArguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        parsed = ReplaceInFileArguments.model_validate(arguments)
        path = resolve_workspace_path(context.workspace, parsed.path)
        if not path.is_file():
            return ToolResult.error("not_a_file", "替换目标不是普通文件")
        try:
            before = read_utf8_text(path)
        except UnsupportedTextFile as exc:
            return ToolResult.error("unsupported_file", str(exc))
        count = before.count(parsed.old_text)
        if count == 0:
            return ToolResult.error("text_not_found", "文件中不存在要替换的旧文本")
        if count > 1 and not parsed.replace_all:
            return ToolResult.error(
                "multiple_matches",
                f"旧文本共匹配 {count} 处，未执行任何写入",
                metadata={"match_count": count},
            )

        replacements = count if parsed.replace_all else 1
        after = before.replace(parsed.old_text, parsed.new_text, replacements)
        relative = path.relative_to(context.workspace).as_posix()
        diff = unified_text_diff(relative, before, after)
        atomic_write_text(path, after)
        return ToolResult.success(
            f"已在 {relative} 替换 {replacements} 处文本",
            output=diff,
            metadata={"path": relative, "replacements": replacements, "diff": diff},
            modified_files=(relative,),
            workspace_changed=before != after,
        )

