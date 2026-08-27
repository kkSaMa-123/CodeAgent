from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import AppServices, create_app
from app.config import ModelConfigurationStatus


def ready_config() -> ModelConfigurationStatus:
    return ModelConfigurationStatus(
        ready=True,
        summary={
            "provider": "fake",
            "base_url": "http://fake.local",
            "model": "fake-model",
            "api_key_configured": True,
        },
    )


def test_health_and_cors_only_allow_local_frontend() -> None:
    app = create_app(AppServices(config_inspector=ready_config))
    with TestClient(app) as client:
        health = client.get("/api/health")
        allowed = client.options(
            "/api/health",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = client.options(
            "/api/health",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert health.json() == {"status": "ok"}
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_config_workspace_session_and_snapshot_do_not_expose_key(tmp_path: Path) -> None:
    app = create_app(AppServices(config_inspector=ready_config))
    with TestClient(app) as client:
        config = client.get("/api/config/status")
        validated = client.post("/api/workspaces/validate", json={"path": str(tmp_path)})
        created = client.post("/api/sessions", json={"workspace": str(tmp_path)})
        snapshot = client.get(f"/api/sessions/{created.json()['session_id']}")

    assert config.status_code == 200
    assert "api_key" not in config.text.lower().replace("api_key_configured", "")
    assert validated.json()["path"] == str(tmp_path.resolve())
    assert created.status_code == 201
    assert created.json()["status"] == "queued"
    assert snapshot.json() == created.json()


def test_invalid_workspace_and_missing_session_have_clear_status(tmp_path: Path) -> None:
    app = create_app(AppServices(config_inspector=ready_config))
    with TestClient(app) as client:
        invalid = client.post(
            "/api/workspaces/validate",
            json={"path": str(tmp_path / "missing")},
        )
        missing = client.get("/api/sessions/missing")

    assert invalid.status_code == 404
    assert invalid.json()["detail"]["error"] == "workspace_not_found"
    assert missing.status_code == 404

