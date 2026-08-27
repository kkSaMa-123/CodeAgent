"""会话状态、终止原因和可回放事件。"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.providers.redaction import SecretRedactor
from app.providers.types import ChatMessage


class SessionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TerminationReason(StrEnum):
    COMPLETED = "completed"
    MAX_ITERATIONS = "max_iterations"
    TASK_TIMEOUT = "task_timeout"
    CANCELLED = "cancelled"
    REPEATED_TOOL_CALL = "repeated_tool_call"
    APPROVAL_DENIED = "approval_denied"
    PROVIDER_ERROR = "provider_error"
    INTERNAL_ERROR = "internal_error"


TERMINAL_STATUSES = frozenset(
    {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED}
)

ALLOWED_TRANSITIONS: Mapping[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.QUEUED: frozenset(
        {SessionStatus.RUNNING, SessionStatus.FAILED, SessionStatus.CANCELLED}
    ),
    SessionStatus.RUNNING: frozenset(
        {
            SessionStatus.WAITING_APPROVAL,
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        }
    ),
    SessionStatus.WAITING_APPROVAL: frozenset(
        {SessionStatus.RUNNING, SessionStatus.FAILED, SessionStatus.CANCELLED}
    ),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.FAILED: frozenset(),
    SessionStatus.CANCELLED: frozenset(),
}

TERMINAL_EVENT_TYPES: Mapping[SessionStatus, str] = {
    SessionStatus.COMPLETED: "task.completed",
    SessionStatus.FAILED: "task.failed",
    SessionStatus.CANCELLED: "task.cancelled",
}


class InvalidStateTransition(RuntimeError):
    """会话状态不允许按请求方式变化。"""


@dataclass(frozen=True, slots=True)
class AgentEvent:
    session_id: str | None
    sequence: int
    event_type: str
    timestamp: datetime
    payload: Mapping[str, Any]


class EventBuffer:
    """保留最近事件，同时保持会话内序号单调递增。"""

    def __init__(
        self,
        capacity: int = 256,
        *,
        session_id: str | None = None,
        redactor: SecretRedactor | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("event buffer capacity must be positive")
        self._events: deque[AgentEvent] = deque(maxlen=capacity)
        self._next_sequence = 1
        self._session_id = session_id
        self._redactor = redactor or SecretRedactor()

    def bind(self, session_id: str) -> None:
        if self._session_id is not None and self._session_id != session_id:
            raise ValueError("event buffer is already bound to another session")
        self._session_id = session_id

    @property
    def capacity(self) -> int:
        return self._events.maxlen or 0

    @property
    def latest_sequence(self) -> int:
        return self._next_sequence - 1

    @property
    def earliest_sequence(self) -> int | None:
        return self._events[0].sequence if self._events else None

    def publish(self, event_type: str, payload: Mapping[str, Any] | None = None) -> AgentEvent:
        event = AgentEvent(
            session_id=self._session_id,
            sequence=self._next_sequence,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            payload=MappingProxyType(self._redactor.redact_value(dict(payload or {}))),
        )
        self._next_sequence += 1
        self._events.append(event)
        return event

    def snapshot(self) -> tuple[AgentEvent, ...]:
        return tuple(self._events)

    def after(self, sequence: int) -> tuple[AgentEvent, ...]:
        return tuple(event for event in self._events if event.sequence > sequence)


@dataclass(slots=True)
class SessionState:
    session_id: str
    workspace: Path
    status: SessionStatus = SessionStatus.QUEUED
    messages: list[ChatMessage] = field(default_factory=list)
    events: EventBuffer = field(default_factory=EventBuffer)
    iteration: int = 0
    termination_reason: TerminationReason | None = None
    final_answer: str | None = None
    workspace_version: int = 0
    modified_files: set[str] = field(default_factory=set)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _terminal_event_emitted: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.events.bind(self.session_id)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def cancellation_requested(self) -> bool:
        return self.cancel_event.is_set()

    def request_cancel(self) -> None:
        self.cancel_event.set()

    def publish(self, event_type: str, payload: Mapping[str, Any] | None = None) -> AgentEvent:
        return self.events.publish(event_type, payload)

    def transition(
        self,
        new_status: SessionStatus,
        *,
        reason: TerminationReason | None = None,
    ) -> None:
        if new_status not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidStateTransition(f"cannot transition from {self.status} to {new_status}")
        if new_status in TERMINAL_STATUSES and reason is None:
            raise InvalidStateTransition("terminal transition requires a reason")
        if new_status not in TERMINAL_STATUSES and reason is not None:
            raise InvalidStateTransition("non-terminal transition cannot set a termination reason")

        previous = self.status
        self.status = new_status
        self.publish(
            "state.changed",
            {"previous": previous.value, "current": new_status.value},
        )

        if new_status in TERMINAL_STATUSES:
            if self._terminal_event_emitted:
                raise InvalidStateTransition("terminal event already emitted")
            self.termination_reason = reason
            self.publish(
                TERMINAL_EVENT_TYPES[new_status],
                {"reason": reason.value if reason is not None else None},
            )
            self._terminal_event_emitted = True
