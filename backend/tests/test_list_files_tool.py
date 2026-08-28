from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.tools.base import ToolContext
from app.tools.discovery import ListFilesArguments, ListFilesTool


def run_list(workspace: Path, **values: object) -> dict[str, object]:
    context = ToolContext("session", workspace, lambda: False)
    arguments = ListFilesArguments.model_validate(values)
    result = asyncio.run(ListFilesTool().execute(arguments, context))
    assert result.status == "success"
    return json.loads(result.output)


def test_list_files_is_sorted_and_respects_depth(tmp_path: Path) -> None:
    (tmp_path / "z.py").write_text("z")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.py").write_text("b")
    (tmp_path / "a" / "nested").mkdir()
    (tmp_path / "a" / "nested" / "deep.py").write_text("deep")

    shallow = run_list(tmp_path, depth=1)
    deep = run_list(tmp_path, depth=2)

    assert [entry["path"] for entry in shallow["entries"]] == ["a", "z.py"]
    assert [entry["path"] for entry in deep["entries"]] == [
        "a",
        "a/b.py",
        "a/nested",
        "z.py",
    ]


def test_list_files_ignores_noise_directories(tmp_path: Path) -> None:
    for name in (".git", "node_modules", ".venv", "dist", "__pycache__"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "ignored.txt").write_text("ignored")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("main")

    payload = run_list(tmp_path, depth=4)
    paths = [entry["path"] for entry in payload["entries"]]

    assert paths == ["src", "src/main.py"]


def test_list_files_applies_entry_limit(tmp_path: Path) -> None:
    for index in range(5):
        (tmp_path / f"{index}.txt").write_text(str(index))

    payload = run_list(tmp_path, depth=1, max_entries=2)

    assert payload["count"] == 2
    assert payload["truncated"] is True


def test_list_files_does_not_follow_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)

    payload = run_list(tmp_path, depth=3)

    assert payload["entries"] == [{"path": "link", "type": "symlink"}]
