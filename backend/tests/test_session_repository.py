from __future__ import annotations

import asyncio
from pathlib import Path

from app.agent.repository import (
    InMemorySessionRepository,
    SessionAlreadyExistsError,
    SessionNotFoundError,
)
from app.providers.types import ChatMessage


def test_create_get_and_list_resolve_workspace(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = InMemorySessionRepository()
        state = await repository.create(tmp_path / "alpha" / "..", session_id="session-a")

        assert await repository.get("session-a") is state
        assert state.workspace == tmp_path.resolve()
        assert await repository.list() == (state,)

    asyncio.run(scenario())


def test_missing_and_duplicate_session_are_explicit(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = InMemorySessionRepository()
        await repository.create(tmp_path, session_id="same")

        try:
            await repository.create(tmp_path, session_id="same")
        except SessionAlreadyExistsError:
            pass
        else:
            raise AssertionError("duplicate session should fail")

        try:
            await repository.get("missing")
        except SessionNotFoundError:
            pass
        else:
            raise AssertionError("missing session should fail")

    asyncio.run(scenario())


def test_two_concurrent_sessions_do_not_contaminate_each_other(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = InMemorySessionRepository()
        first = await repository.create(tmp_path / "first", session_id="first")
        second = await repository.create(tmp_path / "second", session_id="second")
        barrier = asyncio.Barrier(2)

        async def mutate(session_id: str, marker: str) -> None:
            async with repository.locked(session_id) as state:
                await barrier.wait()
                state.messages.append(ChatMessage.user(marker))
                state.modified_files.add(f"{marker}.txt")
                state.publish("test.mutated", {"marker": marker})

        await asyncio.gather(mutate("first", "alpha"), mutate("second", "beta"))

        assert first.workspace == (tmp_path / "first").resolve()
        assert second.workspace == (tmp_path / "second").resolve()
        assert first.messages == [ChatMessage.user("alpha")]
        assert second.messages == [ChatMessage.user("beta")]
        assert first.modified_files == {"alpha.txt"}
        assert second.modified_files == {"beta.txt"}
        assert first.events.snapshot()[0].payload["marker"] == "alpha"
        assert second.events.snapshot()[0].payload["marker"] == "beta"

    asyncio.run(scenario())
