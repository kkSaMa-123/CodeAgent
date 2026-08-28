from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from app.agent.runtime import AgentRuntime
from app.agent.state import SessionState, SessionStatus
from app.providers.fake import FakeProvider
from app.providers.types import AssistantTurn, ToolCall
from app.tools.base import ToolContext
from app.tools.editing import WriteFileArguments, WriteFileTool
from app.tools.git_tools import GitDiffArguments, GitDiffTool
from app.tools.registry import ToolRegistry


def git(workspace: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(workspace), *arguments], check=True, capture_output=True)


def initialize_repository(workspace: Path) -> None:
    git(workspace, "init", "-q")
    git(workspace, "config", "user.email", "test@example.com")
    git(workspace, "config", "user.name", "Test User")
    (workspace / "tracked.txt").write_text("before\n")
    git(workspace, "add", "tracked.txt")
    git(workspace, "commit", "-qm", "initial")


def test_git_diff_includes_tracked_changes_and_untracked_files(tmp_path: Path) -> None:
    initialize_repository(tmp_path)
    writer = WriteFileTool()
    tool_context = ToolContext("session", tmp_path, lambda: False)
    asyncio.run(
        writer.execute(
            WriteFileArguments(path="tracked.txt", content="after\n"),
            tool_context,
        )
    )
    asyncio.run(
        writer.execute(
            WriteFileArguments(path="new.txt", content="new file\n"),
            tool_context,
        )
    )

    result = asyncio.run(GitDiffTool().execute(GitDiffArguments(), tool_context))

    assert result.status == "success"
    assert "-before" in result.output
    assert "+after" in result.output
    assert "new.txt" in result.output
    assert "+new file" in result.output
    assert result.metadata["untracked_files"] == ("new.txt",)


def test_runtime_collects_modified_files_from_write_results(tmp_path: Path) -> None:
    calls = (
        ToolCall(
            id="write-a",
            name="write_file",
            raw_arguments="{}",
            arguments={"path": "a.txt", "content": "a"},
        ),
        ToolCall(
            id="write-b",
            name="write_file",
            raw_arguments="{}",
            arguments={"path": "nested/b.txt", "content": "b"},
        ),
    )
    provider = FakeProvider(AssistantTurn(tool_calls=calls), AssistantTurn(content="done"))
    runtime = AgentRuntime(
        provider,
        ToolRegistry([WriteFileTool()]),
        system_prompt="system",
    )
    state = asyncio.run(runtime.run(SessionState("files", tmp_path), "write files"))

    assert state.status is SessionStatus.COMPLETED
    assert state.modified_files == {"a.txt", "nested/b.txt"}
    assert state.workspace_version == 2
