from pathlib import Path

from app.agent.change_tracker import RunChangeTracker


def test_tracker_freezes_add_modify_delete_rename_and_binary(tmp_path: Path) -> None:
    (tmp_path / "modify.txt").write_text("old\n")
    (tmp_path / "delete.txt").write_text("gone\n")
    (tmp_path / "rename.txt").write_text("same\n")
    tracker = RunChangeTracker(tmp_path, max_preview_bytes=32)
    tracker.start()
    (tmp_path / "modify.txt").write_text("new\nline\n")
    (tmp_path / "delete.txt").unlink()
    (tmp_path / "rename.txt").rename(tmp_path / "renamed.txt")
    (tmp_path / "added.txt").write_text("added\n")
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01")
    (tmp_path / "large.txt").write_text("x" * 100)
    changes = {item["path"]: item for item in tracker.finish()}
    assert changes["modify.txt"]["change_type"] == "modified"
    assert "+line" in changes["modify.txt"]["diff"]
    assert changes["delete.txt"]["preview"] == "gone\n"
    assert changes["renamed.txt"]["old_path"] == "rename.txt"
    assert changes["binary.bin"]["preview_kind"] == "binary"
    assert changes["large.txt"]["preview_kind"] == "oversized"


def test_old_result_does_not_change_after_later_edit(tmp_path: Path) -> None:
    path = tmp_path / "file.py"
    path.write_text("a = 1\n")
    tracker = RunChangeTracker(tmp_path)
    tracker.start()
    path.write_text("a = 2\n")
    frozen = tracker.finish()[0]
    path.write_text("a = 3\n")
    assert frozen["preview"] == "a = 2\n"
    assert "+a = 2" in frozen["diff"]


def test_runtime_credentials_and_dependencies_are_excluded(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("LLM_API_KEY=secret")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "history.sqlite3-wal").write_text("before")
    tracker = RunChangeTracker(tmp_path)
    tracker.start()
    (tmp_path / ".env").write_text("LLM_API_KEY=changed")
    (tmp_path / "runtime" / "history.sqlite3-wal").write_text("after")
    assert tracker.finish() == []
