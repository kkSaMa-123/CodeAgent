"""不依赖 Git 的有界运行文件快照与历史 Diff。"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

IGNORED_PARTS = {
    ".git",
    ".agents",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "runtime",
    "workspaces",
    "__pycache__",
    ".pytest_cache",
}
IGNORED_FILES = {".env", ".DS_Store"}


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    digest: str
    size: int
    content: bytes | None
    is_text: bool


class RunChangeTracker:
    def __init__(
        self,
        workspace: Path,
        *,
        max_files: int = 5000,
        max_total_bytes: int = 8_000_000,
        max_preview_bytes: int = 256_000,
    ) -> None:
        self.workspace = workspace.resolve()
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes
        self.max_preview_bytes = max_preview_bytes
        self._before: dict[str, SnapshotEntry] = {}

    def start(self) -> None:
        self._before = self._snapshot()

    def finish(self) -> list[dict[str, Any]]:
        after = self._snapshot()
        deleted = set(self._before) - set(after)
        added = set(after) - set(self._before)
        renamed: dict[str, str] = {}
        for old_path in sorted(deleted):
            match = next(
                (
                    new_path
                    for new_path in sorted(added)
                    if after[new_path].digest == self._before[old_path].digest
                ),
                None,
            )
            if match:
                renamed[old_path] = match
                added.remove(match)
        changes: list[dict[str, Any]] = []
        for old_path, new_path in renamed.items():
            changes.append(
                self._change(new_path, self._before[old_path], after[new_path], "renamed", old_path)
            )
            deleted.remove(old_path)
        for path in sorted(deleted):
            changes.append(self._change(path, self._before[path], None, "deleted"))
        for path in sorted(added):
            changes.append(self._change(path, None, after[path], "added"))
        for path in sorted(set(self._before) & set(after)):
            if self._before[path].digest != after[path].digest:
                changes.append(self._change(path, self._before[path], after[path], "modified"))
        return changes

    def _snapshot(self) -> dict[str, SnapshotEntry]:
        result: dict[str, SnapshotEntry] = {}
        retained = 0
        for path in sorted(self.workspace.rglob("*")):
            if len(result) >= self.max_files or not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(self.workspace)
            if path.name in IGNORED_FILES or any(part in IGNORED_PARTS for part in relative.parts):
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            size = len(data)
            digest = hashlib.sha256(data).hexdigest()
            is_text = b"\x00" not in data[:8192]
            content = None
            if (
                is_text
                and size <= self.max_preview_bytes
                and retained + size <= self.max_total_bytes
            ):
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    is_text = False
                else:
                    content = data
                    retained += size
            result[relative.as_posix()] = SnapshotEntry(digest, size, content, is_text)
        return result

    def _change(
        self,
        path: str,
        before: SnapshotEntry | None,
        after: SnapshotEntry | None,
        kind: str,
        old_path: str | None = None,
    ) -> dict[str, Any]:
        before_text = self._text(before)
        after_text = self._text(after)
        diff: str | None = None
        additions = deletions = 0
        if before_text is not None and after_text is not None:
            lines = list(
                difflib.unified_diff(
                    before_text.splitlines(keepends=True),
                    after_text.splitlines(keepends=True),
                    fromfile=old_path or path,
                    tofile=path,
                )
            )
            diff = "".join(lines)
            additions = sum(
                1 for line in lines if line.startswith("+") and not line.startswith("+++")
            )
            deletions = sum(
                1 for line in lines if line.startswith("-") and not line.startswith("---")
            )
        elif kind == "added" and after_text is not None:
            additions = len(after_text.splitlines())
            diff = "".join(
                difflib.unified_diff(
                    [], after_text.splitlines(keepends=True), fromfile="/dev/null", tofile=path
                )
            )
        elif kind == "deleted" and before_text is not None:
            deletions = len(before_text.splitlines())
            diff = "".join(
                difflib.unified_diff(
                    before_text.splitlines(keepends=True), [], fromfile=path, tofile="/dev/null"
                )
            )
        preview = after_text if after is not None else before_text
        entry = after or before
        preview_kind = "text"
        if preview is None:
            preview_kind = "binary" if entry is not None and not entry.is_text else "oversized"
        return {
            "path": path,
            "old_path": old_path,
            "change_type": kind,
            "additions": additions,
            "deletions": deletions,
            "before_hash": before.digest if before else None,
            "after_hash": after.digest if after else None,
            "before_size": before.size if before else None,
            "after_size": after.size if after else None,
            "diff": diff,
            "preview": preview,
            "preview_kind": preview_kind,
        }

    @staticmethod
    def _text(entry: SnapshotEntry | None) -> str | None:
        return entry.content.decode("utf-8") if entry and entry.content is not None else None
