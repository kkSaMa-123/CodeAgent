from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agent.tools import ToolExecutionContext
from app.providers.types import ToolCall
from app.services import WorkspaceFileService
from app.tools.defaults import build_file_tool_registry
from app.tools.paths import WorkspaceError, WorkspaceErrorCode


def call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        id=f"call-{name}",
        name=name,
        raw_arguments="{}",
        arguments=arguments,
    )


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("list_files", {"path": "../outside"}),
        ("read_file", {"path": "../outside/secret.txt"}),
        ("search_text", {"query": "secret", "path": "../outside"}),
        ("write_file", {"path": "../outside/new.txt", "content": "stolen"}),
        (
            "replace_in_file",
            {"path": "../outside/secret.txt", "old_text": "secret", "new_text": "changed"},
        ),
        ("git_diff", {"path": "../outside"}),
    ],
)
def test_every_file_tool_rejects_parent_escape(
    tmp_path: Path,
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    registry = build_file_tool_registry()
    context = ToolExecutionContext("session", workspace, lambda: False)

    result = asyncio.run(registry.execute(call(tool_name, arguments), context))

    assert result.error_type == "path_outside_workspace"
    assert (outside / "secret.txt").read_text() == "secret"
    assert not (outside / "new.txt").exists()


def test_tools_and_file_service_both_reject_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    service = WorkspaceFileService(workspace)

    with pytest.raises(WorkspaceError) as error:
        service.read_text("escape/secret.txt")
    assert error.value.code is WorkspaceErrorCode.PATH_OUTSIDE_WORKSPACE

    registry = build_file_tool_registry()
    context = ToolExecutionContext("session", workspace, lambda: False)
    read_result = asyncio.run(
        registry.execute(call("read_file", {"path": "escape/secret.txt"}), context)
    )
    write_result = asyncio.run(
        registry.execute(
            call("write_file", {"path": "escape/new.txt", "content": "unsafe"}),
            context,
        )
    )

    assert read_result.error_type == "path_outside_workspace"
    assert write_result.error_type == "path_outside_workspace"
    assert not (outside / "new.txt").exists()


def test_default_registry_contains_every_local_tool() -> None:
    names = {
        definition["function"]["name"] for definition in build_file_tool_registry().definitions
    }

    assert names == {
        "list_files",
        "read_file",
        "search_text",
        "write_file",
        "replace_in_file",
        "git_diff",
        "run_command",
    }
