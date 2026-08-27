from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.paths import (
    WorkspaceError,
    WorkspaceErrorCode,
    resolve_workspace_path,
    validate_workspace,
)


def test_validate_workspace_normalizes_existing_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()

    assert validate_workspace(nested / ".") == nested.resolve()


@pytest.mark.parametrize(
    ("relative_path", "code"),
    [
        ("../secret.txt", WorkspaceErrorCode.PATH_OUTSIDE_WORKSPACE),
        ("safe/../secret.txt", WorkspaceErrorCode.PATH_OUTSIDE_WORKSPACE),
        ("/tmp/secret.txt", WorkspaceErrorCode.ABSOLUTE_PATH),
        (r"C:\\secret.txt", WorkspaceErrorCode.ABSOLUTE_PATH),
        ("bad\x00path", WorkspaceErrorCode.INVALID_PATH),
    ],
)
def test_rejects_unsafe_tool_paths(
    tmp_path: Path,
    relative_path: str,
    code: WorkspaceErrorCode,
) -> None:
    with pytest.raises(WorkspaceError) as error:
        resolve_workspace_path(tmp_path, relative_path, must_exist=False)

    assert error.value.code is code


def test_similar_directory_prefix_is_not_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sibling = tmp_path / "project-other"
    workspace.mkdir()
    sibling.mkdir()
    (sibling / "secret.txt").write_text("secret")

    with pytest.raises(WorkspaceError) as error:
        resolve_workspace_path(workspace, "../project-other/secret.txt")

    assert error.value.code is WorkspaceErrorCode.PATH_OUTSIDE_WORKSPACE


def test_rejects_symlink_that_escapes_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (workspace / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceError) as error:
        resolve_workspace_path(workspace, "escape/secret.txt")

    assert error.value.code is WorkspaceErrorCode.PATH_OUTSIDE_WORKSPACE


def test_nonexistent_child_is_allowed_only_when_requested(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError) as error:
        resolve_workspace_path(tmp_path, "new/file.txt")
    assert error.value.code is WorkspaceErrorCode.NOT_FOUND

    assert resolve_workspace_path(tmp_path, "new/file.txt", must_exist=False) == (
        tmp_path / "new/file.txt"
    )

