from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import AppServices, create_app
from app.config import ModelConfigurationStatus


def ready() -> ModelConfigurationStatus:
    return ModelConfigurationStatus(ready=True, summary={})


def git(workspace: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(workspace), *arguments], check=True, capture_output=True)


def test_file_tree_preview_and_diff(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "main.py").write_text("before\n")
    git(tmp_path, "add", "main.py")
    git(tmp_path, "commit", "-qm", "initial")
    (tmp_path / "main.py").write_text("after\n")

    app = create_app(AppServices(config_inspector=ready))
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"workspace": str(tmp_path)}).json()
        prefix = f"/api/sessions/{session['session_id']}"
        tree = client.get(f"{prefix}/files/tree", params={"depth": 2})
        content = client.get(f"{prefix}/files/content", params={"path": "main.py"})
        diff = client.get(f"{prefix}/diff")

    assert tree.status_code == 200
    assert any(entry["path"] == "main.py" for entry in tree.json()["entries"])
    assert content.json() == {"path": "main.py", "content": "after\n", "total_lines": 1}
    assert "-before" in diff.json()["diff"]
    assert "+after" in diff.json()["diff"]


@pytest.mark.parametrize(
    ("endpoint", "path"),
    [
        ("files/tree", "../outside"),
        ("files/content", "../outside/secret.txt"),
        ("files/content", "/etc/passwd"),
        ("files/content", "bad\x00path"),
        ("diff", "../outside"),
    ],
)
def test_file_apis_reject_every_path_escape(
    tmp_path: Path,
    endpoint: str,
    path: str,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    app = create_app(AppServices(config_inspector=ready))
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"workspace": str(workspace)}).json()
        response = client.get(
            f"/api/sessions/{session['session_id']}/{endpoint}",
            params={"path": path},
        )

    assert response.status_code == 400
    assert "secret" not in response.text


def test_file_api_rejects_escaping_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    app = create_app(AppServices(config_inspector=ready))

    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"workspace": str(workspace)}).json()
        response = client.get(
            f"/api/sessions/{session['session_id']}/files/content",
            params={"path": "escape/secret.txt"},
        )

    assert response.status_code == 400
    assert "secret" not in response.text

