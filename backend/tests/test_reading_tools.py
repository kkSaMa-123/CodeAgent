from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tools.base import ToolContext
from app.tools.reading import (
    ReadFileArguments,
    ReadFileTool,
    SearchTextArguments,
    SearchTextTool,
)


def context(workspace: Path) -> ToolContext:
    return ToolContext("session", workspace, lambda: False)


def test_read_file_returns_numbered_range_and_total(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("one\ntwo\nthree\nfour\n")
    arguments = ReadFileArguments(path="main.py", start_line=2, end_line=3)

    result = asyncio.run(ReadFileTool().execute(arguments, context(tmp_path)))

    assert result.status == "success"
    assert result.output == "     2 | two\n     3 | three"
    assert result.metadata == {
        "path": "main.py",
        "start_line": 2,
        "end_line": 3,
        "total_lines": 4,
    }


def test_read_file_validates_range_boundaries(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ReadFileArguments(path="x", start_line=0)
    with pytest.raises(ValidationError):
        ReadFileArguments(path="x", start_line=3, end_line=2)
    with pytest.raises(ValidationError):
        ReadFileArguments(path="x", start_line=1, end_line=501)

    (tmp_path / "short.txt").write_text("only\n")
    result = asyncio.run(
        ReadFileTool().execute(
            ReadFileArguments(path="short.txt", start_line=2),
            context(tmp_path),
        )
    )
    assert result.error_type == "line_out_of_range"


def test_read_file_rejects_binary_and_invalid_utf8(tmp_path: Path) -> None:
    (tmp_path / "binary.bin").write_bytes(b"hello\x00world")
    (tmp_path / "invalid.txt").write_bytes(b"\xff\xfe")

    binary = asyncio.run(
        ReadFileTool().execute(ReadFileArguments(path="binary.bin"), context(tmp_path))
    )
    invalid = asyncio.run(
        ReadFileTool().execute(ReadFileArguments(path="invalid.txt"), context(tmp_path))
    )

    assert binary.error_type == "unsupported_file"
    assert invalid.error_type == "unsupported_file"
    assert binary.output == ""
    assert invalid.output == ""


def test_search_text_returns_paths_lines_and_applies_limit(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("needle one\nnone\nneedle two\n")
    (tmp_path / "b.py").write_text("Needle three\nneedle four\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored").write_text("needle hidden")

    result = asyncio.run(
        SearchTextTool().execute(
            SearchTextArguments(query="needle", max_results=2),
            context(tmp_path),
        )
    )
    payload = json.loads(result.output)

    assert payload["matches"] == [
        {"line": 1, "path": "a.py", "text": "needle one"},
        {"line": 3, "path": "a.py", "text": "needle two"},
    ]
    assert payload["truncated"] is True


def test_search_text_can_be_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "main.txt").write_text("Hello World\n")
    result = asyncio.run(
        SearchTextTool().execute(
            SearchTextArguments(query="hello", case_sensitive=False),
            context(tmp_path),
        )
    )

    assert json.loads(result.output)["matches"][0]["line"] == 1
