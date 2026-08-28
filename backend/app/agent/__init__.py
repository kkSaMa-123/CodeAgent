"""CodeAgent 手写运行时的领域模型。"""

from app.agent.change_tracker import RunChangeTracker
from app.agent.context import ContextWindow, ConversationContext, truncate_text
from app.agent.repetition import RepetitionDecision, RepetitionGuard
from app.agent.runtime import AgentRuntime, RuntimeLimits
from app.agent.state import (
    AgentEvent,
    EventBuffer,
    InvalidStateTransition,
    RunState,
    SessionState,
    SessionStatus,
    TerminationReason,
)
from app.agent.tools import ToolExecutionContext, ToolExecutionResult, ToolExecutor

__all__ = [
    "AgentEvent",
    "AgentRuntime",
    "ContextWindow",
    "ConversationContext",
    "EventBuffer",
    "InvalidStateTransition",
    "RepetitionDecision",
    "RepetitionGuard",
    "RuntimeLimits",
    "RunChangeTracker",
    "RunState",
    "SessionState",
    "SessionStatus",
    "TerminationReason",
    "ToolExecutionContext",
    "ToolExecutionResult",
    "ToolExecutor",
    "truncate_text",
]
