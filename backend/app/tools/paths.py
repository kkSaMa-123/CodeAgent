"""所有文件工具和文件 API 共用的工作区边界。"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path, PureWindowsPath


class WorkspaceErrorCode(StrEnum):
    INVALID_WORKSPACE = "invalid_workspace"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    WORKSPACE_NOT_DIRECTORY = "workspace_not_directory"
    WORKSPACE_NOT_ACCESSIBLE = "workspace_not_accessible"
    INVALID_PATH = "invalid_path"
    ABSOLUTE_PATH = "absolute_path_not_allowed"
    PATH_OUTSIDE_WORKSPACE = "path_outside_workspace"
    NOT_FOUND = "not_found"


class WorkspaceError(ValueError):
    def __init__(self, code: WorkspaceErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject_nul(value: str, *, workspace: bool = False) -> None:
    if "\x00" in value:
        code = (
            WorkspaceErrorCode.INVALID_WORKSPACE if workspace else WorkspaceErrorCode.INVALID_PATH
        )
        raise WorkspaceError(code, "路径不能包含 NUL 字符")


def validate_workspace(workspace: str | Path) -> Path:
    """校验用户选择的根目录并返回规范化绝对路径。"""

    raw = os.fspath(workspace)
    _reject_nul(raw, workspace=True)
    path = Path(raw).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise WorkspaceError(
            WorkspaceErrorCode.WORKSPACE_NOT_FOUND,
            "工作区目录不存在",
        ) from exc
    except OSError as exc:
        raise WorkspaceError(
            WorkspaceErrorCode.INVALID_WORKSPACE,
            "无法解析工作区目录",
        ) from exc
    if not resolved.is_dir():
        raise WorkspaceError(
            WorkspaceErrorCode.WORKSPACE_NOT_DIRECTORY,
            "工作区必须是目录",
        )
    if not os.access(resolved, os.R_OK | os.X_OK):
        raise WorkspaceError(
            WorkspaceErrorCode.WORKSPACE_NOT_ACCESSIBLE,
            "工作区不可读取或遍历",
        )
    return resolved


def resolve_workspace_path(
    workspace: str | Path,
    relative_path: str | Path,
    *,
    must_exist: bool = True,
) -> Path:
    """将工具的相对路径安全解析到工作区内。"""

    root = validate_workspace(workspace)
    raw = os.fspath(relative_path)
    _reject_nul(raw)
    supplied = Path(raw)
    if supplied.is_absolute() or PureWindowsPath(raw).is_absolute():
        raise WorkspaceError(
            WorkspaceErrorCode.ABSOLUTE_PATH,
            "工具路径必须相对于工作区",
        )
    if ".." in supplied.parts or ".." in PureWindowsPath(raw).parts:
        raise WorkspaceError(
            WorkspaceErrorCode.PATH_OUTSIDE_WORKSPACE,
            "路径不能包含上级目录",
        )

    try:
        candidate = (root / supplied).resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise WorkspaceError(WorkspaceErrorCode.NOT_FOUND, "工作区路径不存在") from exc
    except OSError as exc:
        raise WorkspaceError(WorkspaceErrorCode.INVALID_PATH, "无法解析工具路径") from exc

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError(
            WorkspaceErrorCode.PATH_OUTSIDE_WORKSPACE,
            "路径解析后位于工作区之外",
        ) from exc
    return candidate
