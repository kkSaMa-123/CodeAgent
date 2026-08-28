from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.agent.state import EventBuffer
from app.persistence import SCHEMA_VERSION, ConflictError, RepositoryError, SQLiteRepository
from app.providers.redaction import SecretRedactor


def test_schema_project_conversation_transactions_and_safe_delete(tmp_path: Path) -> None:
    database = tmp_path / "data" / "history.sqlite3"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = workspace / "keep.txt"
    marker.write_text("keep")
    repository = SQLiteRepository(database)
    assert repository.pragmas()["user_version"] == SCHEMA_VERSION
    assert repository.pragmas()["foreign_keys"] == 1
    assert repository.pragmas()["journal_mode"].lower() == "wal"
    project = repository.register_project(workspace, "Demo")
    duplicate = repository.register_project(workspace / ".")
    assert duplicate.id == project.id
    conversation = repository.create_conversation(project.id)
    run = repository.create_run(conversation.id, "first task")
    with pytest.raises(ConflictError):
        repository.create_run(conversation.id, "duplicate")
    with pytest.raises(ConflictError):
        repository.delete_conversation(conversation.id)
    repository.recover_interrupted_runs()
    assert repository.get_run(run["id"])["termination_reason"] == "server_restarted"
    repository.delete_project(project.id)
    assert marker.read_text() == "keep"
    repository.close()

    reopened = SQLiteRepository(database)
    assert reopened.pragmas()["user_version"] == SCHEMA_VERSION
    reopened.close()


def test_unknown_database_version_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    connection.close()
    with pytest.raises(RepositoryError):
        SQLiteRepository(database)


def test_unavailable_project_is_retained(tmp_path: Path) -> None:
    workspace = tmp_path / "moved"
    workspace.mkdir()
    repository = SQLiteRepository(tmp_path / "db.sqlite3")
    project = repository.register_project(workspace)
    workspace.rmdir()
    assert repository.get_project(project.id).available is False
    repository.close()


def test_persisted_events_remove_credentials_and_private_reasoning(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repository = SQLiteRepository(tmp_path / "secure.sqlite3")
    project = repository.register_project(workspace)
    conversation = repository.create_conversation(project.id)
    run = repository.create_run(conversation.id, "secure")
    buffer = EventBuffer(
        session_id=run["id"],
        redactor=SecretRedactor(["sk-real-secret-value"]),
        on_publish=repository.append_event,
    )
    buffer.publish(
        "model.completed",
        {
            "api_key": "sk-real-secret-value",
            "Authorization": "Bearer sk-real-secret-value",
            "reasoning_content": "private chain",
            "summary": "safe sk-real-secret-value",
        },
    )
    raw = (tmp_path / "secure.sqlite3").read_bytes()
    assert b"sk-real-secret-value" not in raw
    assert b"private chain" not in raw
    assert repository.list_events(run["id"])[0]["payload"]["summary"] == "safe [REDACTED]"
    repository.close()
