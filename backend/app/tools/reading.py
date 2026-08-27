"""安全的文本文件分段读取与搜索。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field, model_validator

from app.tools.base import ToolArguments, ToolContext, ToolResult
from app.tools.discovery import walk_workspace
from app.tools.paths import resolve_workspace_path


class UnsupportedTextFile(ValueError):
    pass


def read_utf8_text(path: Path) -> str:
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        raise UnsupportedTextFile("文件包含二进制数据")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedTextFile("文件不是可支持的 UTF-8 文本") from exc


class ReadFileArguments(ToolArguments):
    path: str
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> ReadFileArguments:
        if self.end_line is not None:
            if self.end_line < self.start_line:
                raise ValueError("end_line must not be less than start_line")
            if self.end_line - self.start_line + 1 > 500:
                raise ValueError("a read_file call can return at most 500 lines")
        return self


class ReadFileTool:
    name = "read_file"
    description = "按 1-based 行号范围读取工作区内的 UTF-8 文本文件。"
    arguments_model = ReadFileArguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        parsed = ReadFileArguments.model_validate(arguments)
        path = resolve_workspace_path(context.workspace, parsed.path)
        if not path.is_file():
            return ToolResult.error("not_a_file", "读取目标不是普通文件")
        try:
            text = read_utf8_text(path)
        except UnsupportedTextFile as exc:
            return ToolResult.error("unsupported_file", str(exc))
        lines = text.splitlines()
        total_lines = len(lines)
        if total_lines and parsed.start_line > total_lines:
            return ToolResult.error(
                "line_out_of_range",
                "起始行超出文件范围",
                metadata={"total_lines": total_lines},
            )

        end_line = min(parsed.end_line or (parsed.start_line + 199), total_lines)
        if total_lines == 0:
            actual_start = 0
            end_line = 0
            selected: list[str] = []
        else:
            actual_start = parsed.start_line
            selected = lines[actual_start - 1 : end_line]
        numbered = "\n".join(
            f"{line_number:>6} | {line}"
            for line_number, line in enumerate(selected, start=actual_start)
        )
        metadata = {
            "path": path.relative_to(context.workspace).as_posix(),
            "start_line": actual_start,
            "end_line": end_line,
            "total_lines": total_lines,
        }
        return ToolResult.success(
            f"已读取 {metadata['path']} 第 {actual_start}-{end_line} 行",
            output=numbered,
            metadata=metadata,
        )


class SearchTextArguments(ToolArguments):
    query: str = Field(min_length=1)
    path: str = "."
    max_results: int = Field(default=100, ge=1, le=500)
    case_sensitive: bool = True


class SearchTextTool:
    name = "search_text"
    description = "在工作区 UTF-8 文本中搜索字面文本，返回相对路径和行号。"
    arguments_model = SearchTextArguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        parsed = SearchTextArguments.model_validate(arguments)
        target = resolve_workspace_path(context.workspace, parsed.path)
        files: tuple[Path, ...]
        if target.is_file():
            files = (target,)
        elif target.is_dir():
            entries, _ = walk_workspace(
                context.workspace,
                parsed.path,
                max_depth=10,
                max_entries=10_000,
            )
            files = tuple(
                context.workspace / entry.path for entry in entries if entry.kind == "file"
            )
        else:
            return ToolResult.error("invalid_path", "搜索路径不是文件或目录")

        query = parsed.query if parsed.case_sensitive else parsed.query.casefold()
        matches: list[dict[str, str | int]] = []
        scanned_files = 0
        for file_path in files:
            if len(matches) >= parsed.max_results:
                break
            try:
                text = read_utf8_text(file_path)
            except (OSError, UnsupportedTextFile):
                continue
            scanned_files += 1
            for line_number, line in enumerate(text.splitlines(), start=1):
                haystack = line if parsed.case_sensitive else line.casefold()
                if query in haystack:
                    matches.append(
                        {
                            "path": file_path.relative_to(context.workspace).as_posix(),
                            "line": line_number,
                            "text": line[:500],
                        }
                    )
                    if len(matches) >= parsed.max_results:
                        break

        payload = {
            "query": parsed.query,
            "matches": matches,
            "count": len(matches),
            "scanned_files": scanned_files,
            "truncated": len(matches) >= parsed.max_results,
        }
        return ToolResult.success(
            f"找到 {len(matches)} 处匹配",
            output=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            metadata={"count": len(matches), "truncated": payload["truncated"]},
        )
