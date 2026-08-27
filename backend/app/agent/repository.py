"""内存会话仓库。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from app.agent.state import EventBuffer, SessionState


class SessionNotFoundError(LookupError):
    """指定会话不存在。"""


class SessionAlreadyExistsError(RuntimeError):
    """指定会话标识已被使用。"""


class InMemorySessionRepository:
    """协程安全的进程内会话存储。"""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        workspace: Path,
        *,
        session_id: str | None = None,
        event_capacity: int = 256,
    ) -> SessionState:
        resolved_id = session_id or str(uuid4())
        state = SessionState(
            session_id=resolved_id,
            workspace=workspace.resolve(),
            events=EventBuffer(capacity=event_capacity),
        )
        async with self._lock:
            if resolved_id in self._sessions:
                raise SessionAlreadyExistsError(resolved_id)
            self._sessions[resolved_id] = state
        return state

    async def get(self, session_id: str) -> SessionState:
        async with self._lock:
            try:
                return self._sessions[session_id]
            except KeyError as exc:
                raise SessionNotFoundError(session_id) from exc

    @asynccontextmanager
    async def locked(self, session_id: str) -> AsyncIterator[SessionState]:
        """独占访问单个会话，不阻塞其他会话。"""

        state = await self.get(session_id)
        async with state.lock:
            yield state

    async def list(self) -> tuple[SessionState, ...]:
        async with self._lock:
            return tuple(self._sessions.values())

