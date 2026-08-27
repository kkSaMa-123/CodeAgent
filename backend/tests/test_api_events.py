from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.repository import InMemorySessionRepository
from app.agent.state import SessionStatus, TerminationReason
from app.api import AppServices, create_app
from app.api.application import session_event_stream
from app.config import ModelConfigurationStatus


def ready() -> ModelConfigurationStatus:
    return ModelConfigurationStatus(ready=True, summary={})


def test_sse_sends_monotonic_events_and_last_event_id_replay(tmp_path: Path) -> None:
    repository = InMemorySessionRepository()

    async def prepare():
        state = await repository.create(tmp_path, session_id="events")
        state.transition(SessionStatus.RUNNING)
        state.publish("custom.event", {"value": 1})
        state.transition(SessionStatus.COMPLETED, reason=TerminationReason.COMPLETED)
        return state

    state = asyncio.run(prepare())
    app = create_app(AppServices(repository=repository, config_inspector=ready))
    with TestClient(app) as client:
        all_events = client.get("/api/sessions/events/events")
        replay = client.get(
            "/api/sessions/events/events",
            headers={"Last-Event-ID": "2"},
        )

    assert all_events.status_code == 200
    assert all_events.headers["content-type"].startswith("text/event-stream")
    assert "id: 1" in all_events.text
    assert f"id: {state.events.latest_sequence}" in all_events.text
    assert "id: 1\n" not in replay.text
    assert "id: 2\n" not in replay.text
    assert "state.changed" in replay.text
    assert "custom.event" not in replay.text


def test_buffer_expiry_sends_snapshot_before_retained_events(tmp_path: Path) -> None:
    repository = InMemorySessionRepository()

    async def prepare() -> None:
        state = await repository.create(tmp_path, session_id="expired", event_capacity=2)
        state.transition(SessionStatus.RUNNING)
        state.publish("old.event", {})
        state.transition(SessionStatus.COMPLETED, reason=TerminationReason.COMPLETED)

    asyncio.run(prepare())
    app = create_app(AppServices(repository=repository, config_inspector=ready))
    with TestClient(app) as client:
        response = client.get("/api/sessions/expired/events")

    assert response.text.startswith("event: snapshot")
    assert "task.completed" in response.text
    assert "old.event" not in response.text


def test_empty_live_stream_emits_heartbeat(tmp_path: Path) -> None:
    async def scenario() -> str:
        services = AppServices(config_inspector=ready)
        state = await services.repository.create(tmp_path)
        stream = session_event_stream(state, services, 0, heartbeat_seconds=0.01)
        first = await anext(stream)
        await stream.aclose()
        return first

    assert asyncio.run(scenario()) == ": heartbeat\n\n"
