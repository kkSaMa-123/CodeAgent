from __future__ import annotations

from pathlib import Path

import pytest

from app.agent import (
    EventBuffer,
    InvalidStateTransition,
    SessionState,
    SessionStatus,
    TerminationReason,
)


def make_state() -> SessionState:
    return SessionState(session_id="session-1", workspace=Path("/tmp/workspace"))


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ((SessionStatus.RUNNING, SessionStatus.COMPLETED), TerminationReason.COMPLETED),
        ((SessionStatus.RUNNING, SessionStatus.FAILED), TerminationReason.INTERNAL_ERROR),
        ((SessionStatus.CANCELLED,), TerminationReason.CANCELLED),
        (
            (
                SessionStatus.RUNNING,
                SessionStatus.WAITING_APPROVAL,
                SessionStatus.RUNNING,
                SessionStatus.CANCELLED,
            ),
            TerminationReason.CANCELLED,
        ),
    ],
)
def test_legal_state_transitions(
    path: tuple[SessionStatus, ...],
    reason: TerminationReason,
) -> None:
    state = make_state()

    for status in path:
        state.transition(
            status,
            reason=reason
            if status
            in {
                SessionStatus.COMPLETED,
                SessionStatus.FAILED,
                SessionStatus.CANCELLED,
            }
            else None,
        )

    assert state.status is path[-1]
    assert state.termination_reason is reason


def test_rejects_illegal_or_incomplete_terminal_transitions() -> None:
    state = make_state()

    with pytest.raises(InvalidStateTransition):
        state.transition(SessionStatus.COMPLETED, reason=TerminationReason.COMPLETED)

    state.transition(SessionStatus.RUNNING)
    with pytest.raises(InvalidStateTransition):
        state.transition(SessionStatus.COMPLETED)


def test_terminal_transition_emits_exactly_one_terminal_event() -> None:
    state = make_state()
    state.transition(SessionStatus.RUNNING)
    state.transition(SessionStatus.COMPLETED, reason=TerminationReason.COMPLETED)

    terminal_events = [
        event for event in state.events.snapshot() if event.event_type.startswith("task.")
    ]

    assert len(terminal_events) == 1
    assert terminal_events[0].event_type == "task.completed"
    assert terminal_events[0].session_id == state.session_id
    with pytest.raises(InvalidStateTransition):
        state.transition(SessionStatus.FAILED, reason=TerminationReason.INTERNAL_ERROR)
    assert (
        len([event for event in state.events.snapshot() if event.event_type.startswith("task.")])
        == 1
    )


def test_event_buffer_is_bounded_but_sequences_remain_monotonic() -> None:
    buffer = EventBuffer(capacity=3)

    for index in range(5):
        buffer.publish("test.event", {"index": index})

    events = buffer.snapshot()
    assert [event.sequence for event in events] == [3, 4, 5]
    assert buffer.earliest_sequence == 3
    assert buffer.latest_sequence == 5
    assert [event.sequence for event in buffer.after(3)] == [4, 5]
