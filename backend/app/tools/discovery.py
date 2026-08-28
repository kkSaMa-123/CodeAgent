"""有界工作区文件发现。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from app.tools.base import ToolArguments, ToolContext, ToolResult
from app.tools.paths import resolve_workspace_path

DEFAULT_IGNORED_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "target",
        "venv",
    }
)


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    kind: str
    size: int | None = None

    def as_dict(self) -> dict[str, str | int]:
        result: dict[str, str | int] = {"path": self.path, "type": self.kind}
        if self.size is not None:
            result["size"] = self.size
        return result


def walk_workspace(
    workspace: Path,
    relative_path: str = ".",
    *,
    max_depth: int,
    max_entries: int,
) -> tuple[tuple[FileEntry, ...], bool]:
    root = resolve_workspace_path(workspace, relative_path)
    if not root.is_dir():
        raise NotADirectoryError("列表路径不是目录")

    entries: list[FileEntry] = []
    truncated = False

    def visit(directory: Path, depth: int) -> None:
        nonlocal truncated
        if depth > max_depth or truncated:
            return
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            return
        for child in children:
            if child.name in DEFAULT_IGNORED_NAMES:
                continue
            if len(entries) >= max_entries:
                truncated = True
                return
            relative = child.relative_to(workspace).as_posix()
            if child.is_symlink():
                entries.append(FileEntry(relative, "symlink"))
                continue
            if child.is_dir():
                entries.append(FileEntry(relative, "directory"))
                if depth < max_depth:
                    visit(child, depth + 1)
            elif child.is_file():
                try:
                    size = child.stat().st_size
                except OSError:
                    size = None
                entries.append(FileEntry(relative, "file", size))

    if max_depth > 0:
        visit(root, 1)
    entries.sort(key=lambda entry: entry.path.casefold())
    return tuple(entries), truncated


class ListFilesArguments(ToolArguments):
    path: str = "."
    depth: int = Field(default=3, ge=0, le=10)
    max_entries: int = Field(default=500, ge=1, le=2_000)


class ListFilesTool:
    name = "list_files"
    description = "列出工作区内的文件和目录，默认忽略依赖与构建缓存。"
    arguments_model = ListFilesArguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        parsed = ListFilesArguments.model_validate(arguments)
        entries, truncated = walk_workspace(
            context.workspace,
            parsed.path,
            max_depth=parsed.depth,
            max_entries=parsed.max_entries,
        )
        payload = {
            "path": parsed.path,
            "entries": [entry.as_dict() for entry in entries],
            "count": len(entries),
            "truncated": truncated,
        }
        return ToolResult.success(
            f"已列出 {len(entries)} 个工作区条目",
            output=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            metadata={"count": len(entries), "truncated": truncated},
        )
