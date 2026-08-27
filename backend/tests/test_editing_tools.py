from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.agent.tools import ToolExecutionContext
from app.providers.types import ToolCall
from app.tools.base import ToolContext
from app.tools.editing import (
    ReplaceInFileArguments,
    ReplaceInFileTool,
    WriteFileArguments,
    WriteFileTool,
)
from app.tools.registry import ToolRegistry


def context(workspace: Path) -> ToolContext:
    return ToolContext("session", workspace, lambda: False)


def test_write_file_creates_parent_and_reports_new_file_diff(tmp_path: Path) -> None:
    result = asyncio.run(
        WriteFileTool().execute(
            WriteFileArguments(path="src/main.py", content="print('ok')\n"),
            context(tmp_path),
        )
    )

    assert (tmp_path / "src/main.py").read_text() == "print('ok')\n"
    assert result.status == "success"
    assert result.metadata["created"] is True
    assert "+++ b/src/main.py" in result.output
    assert result.modified_files == ("src/main.py",)


def test_write_file_overwrites_existing_text(tmp_path: Path) -> None:
    path = tmp_path / "main.py"
    path.write_text("old\n")

    result = asyncio.run(
        WriteFileTool().execute(
            WriteFileArguments(path="main.py", content="new\n"),
            context(tmp_path),
        )
    )

    assert path.read_text() == "new\n"
    assert result.metadata["created"] is False
    assert "-old" in result.output
    assert "+new" in result.output


def test_replace_requires_unique_match_by_default(tmp_path: Path) -> None:
    path = tmp_path / "main.txt"
    path.write_text("same\nsame\n")
    tool = ReplaceInFileTool()

    multiple = asyncio.run(
        tool.execute(
            ReplaceInFileArguments(path="main.txt", old_text="same", new_text="changed"),
            context(tmp_path),
        )
    )
    missing = asyncio.run(
        tool.execute(
            ReplaceInFileArguments(path="main.txt", old_text="missing", new_text="changed"),
            context(tmp_path),
        )
    )

    assert multiple.error_type == "multiple_matches"
    assert missing.error_type == "text_not_found"
    assert path.read_text() == "same\nsame\n"


def test_replace_unique_and_explicit_replace_all(tmp_path: Path) -> None:
    path = tmp_path / "main.txt"
    path.write_text("one two two\n")
    tool = ReplaceInFileTool()

    unique = asyncio.run(
        tool.execute(
            ReplaceInFileArguments(path="main.txt", old_text="one", new_text="ONE"),
            context(tmp_path),
        )
    )
    replace_all = asyncio.run(
        tool.execute(
            ReplaceInFileArguments(
                path="main.txt",
                old_text="two",
                new_text="TWO",
                replace_all=True,
            ),
            context(tmp_path),
        )
    )

    assert unique.status == "success"
    assert replace_all.metadata["replacements"] == 2
    assert path.read_text() == "ONE TWO TWO\n"


def test_atomic_replace_failure_keeps_original_and_becomes_tool_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "main.txt"
    path.write_text("original\n")
    registry = ToolRegistry([WriteFileTool()])
    call = ToolCall(
        id="write",
        name="write_file",
        raw_arguments="{}",
        arguments={"path": "main.txt", "content": "replacement\n"},
    )
    tool_context = ToolExecutionContext("session", tmp_path, lambda: False)

    def fail_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    result = asyncio.run(registry.execute(call, tool_context))

    assert result.error_type == "internal_tool_error"
    assert path.read_text() == "original\n"
    assert not list(tmp_path.glob(".main.txt.*.tmp"))

