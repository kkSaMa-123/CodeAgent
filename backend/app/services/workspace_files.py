"""文件 API 的唯一工作区访问入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.tools.discovery import FileEntry, walk_workspace
from app.tools.paths import resolve_workspace_path, validate_workspace
from app.tools.reading import read_utf8_text


@dataclass(frozen=True, slots=True)
class WorkspaceFileService:
    """阶段六的文件树和预览路由必须调用本服务。"""

    workspace: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", validate_workspace(self.workspace))

    def resolve(self, relative_path: str, *, must_exist: bool = True) -> Path:
        return resolve_workspace_path(
            self.workspace,
            relative_path,
            must_exist=must_exist,
        )

    def list_entries(
        self,
        relative_path: str = ".",
        *,
        max_depth: int = 3,
        max_entries: int = 500,
    ) -> tuple[tuple[FileEntry, ...], bool]:
        return walk_workspace(
            self.workspace,
            relative_path,
            max_depth=max_depth,
            max_entries=max_entries,
        )

    def read_text(self, relative_path: str) -> str:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise IsADirectoryError("文件预览目标不是普通文件")
        return read_utf8_text(path)

