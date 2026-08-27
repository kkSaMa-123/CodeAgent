"""不依赖 Agent 框架的单循环运行时。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, replace
from typing import TypeVar

from app.agent.context import ContextWindow, truncate_text
from app.agent.repetition import RepetitionDecision, RepetitionGuard
from app.agent.state import SessionState, SessionStatus, TerminationReason
from app.agent.tools import ToolExecutionContext, ToolExecutionResult, ToolExecutor
from app.providers.base import ModelProvider
from app.providers.errors import ProviderError
from app.providers.types import ChatMessage


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    max_iterations: int = 20
    task_timeout_seconds: float = 300.0
    max_tool_output_chars: int = 20_000
    context_budget_chars: int = 120_000
    repeat_warning_threshold: int = 3
    repeat_stop_threshold: int = 5

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        if self.task_timeout_seconds <= 0:
            raise ValueError("task_timeout_seconds must be positive")
        if self.max_tool_output_chars <= 0:
            raise ValueError("max_tool_output_chars must be positive")
        if self.context_budget_chars <= 0:
            raise ValueError("context_budget_chars must be positive")
        if self.repeat_warning_threshold < 2:
            raise ValueError("repeat_warning_threshold must be at least 2")
        if self.repeat_stop_threshold <= self.repeat_warning_threshold:
            raise ValueError("repeat_stop_threshold must exceed repeat_warning_threshold")


class _RuntimeCancelled(Exception):
    pass


class _RuntimeTimedOut(Exception):
    pass


T = TypeVar("T")


class AgentRuntime:
    def __init__(
        self,
        provider: ModelProvider,
        tools: ToolExecutor,
        *,
        system_prompt: str,
        limits: RuntimeLimits | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._system_prompt = system_prompt
        self._limits = limits or RuntimeLimits()
        self._context_window = ContextWindow(self._limits.context_budget_chars)

    async def run(self, state: SessionState, task: str) -> SessionState:
        if state.status is not SessionStatus.QUEUED:
            raise ValueError("only queued sessions can start a task")

        state.messages.extend([ChatMessage.system(self._system_prompt), ChatMessage.user(task)])
        state.transition(SessionStatus.RUNNING)
        deadline = asyncio.get_running_loop().time() + self._limits.task_timeout_seconds

        try:
            await self._run_loop(state, deadline)
        except _RuntimeCancelled:
            state.transition(SessionStatus.CANCELLED, reason=TerminationReason.CANCELLED)
        except _RuntimeTimedOut:
            state.transition(SessionStatus.FAILED, reason=TerminationReason.TASK_TIMEOUT)
        except ProviderError as exc:
            state.publish(
                "model.error",
                {"kind": exc.kind.value, "retryable": exc.retryable},
            )
            state.transition(SessionStatus.FAILED, reason=TerminationReason.PROVIDER_ERROR)
        except Exception:
            state.transition(SessionStatus.FAILED, reason=TerminationReason.INTERNAL_ERROR)
        return state

    async def _run_loop(self, state: SessionState, deadline: float) -> None:
        repetition = RepetitionGuard(
            warning_threshold=self._limits.repeat_warning_threshold,
            stop_threshold=self._limits.repeat_stop_threshold,
        )
        for iteration in range(1, self._limits.max_iterations + 1):
            self._check_boundary(state, deadline)

            state.iteration = iteration
            state.publish("model.started", {"iteration": iteration})
            turn = await self._await_guarded(
                self._provider.complete(
                    self._context_window.prepare(state.messages),
                    self._tools.definitions,
                ),
                state,
                deadline,
            )
            state.messages.append(turn.as_message())
            state.publish(
                "model.completed",
                {"iteration": iteration, "tool_call_count": len(turn.tool_calls)},
            )

            if not turn.tool_calls:
                state.final_answer = turn.content or ""
                state.transition(SessionStatus.COMPLETED, reason=TerminationReason.COMPLETED)
                return

            context = ToolExecutionContext(
                session_id=state.session_id,
                workspace=state.workspace,
                cancellation_requested=lambda: state.cancellation_requested,
                on_approval_requested=lambda approval: self._approval_requested(
                    state,
                    approval,
                ),
                on_approval_resolved=lambda approval, approved: self._approval_resolved(
                    state,
                    approval,
                    approved,
                ),
            )
            for call in turn.tool_calls:
                self._check_boundary(state, deadline)
                repeat_decision = repetition.check(call, state.workspace_version)
                if repeat_decision is RepetitionDecision.STOP:
                    state.publish(
                        "tool.repeated",
                        {
                            "tool_call_id": call.id,
                            "name": call.name,
                            "count": repetition.consecutive_count,
                            "action": "stop",
                        },
                    )
                    state.transition(
                        SessionStatus.FAILED,
                        reason=TerminationReason.REPEATED_TOOL_CALL,
                    )
                    return

                state.publish("tool.started", {"tool_call_id": call.id, "name": call.name})
                if repeat_decision is RepetitionDecision.WARN:
                    result = ToolExecutionResult.error(
                        "相同工具和参数已在未变化的工作区上连续调用，"
                        "请调整参数或采取能产生新信息的操作。",
                        error_type="repeated_tool_call",
                        summary="检测到无进展的重复调用",
                    )
                    state.publish(
                        "tool.repeated",
                        {
                            "tool_call_id": call.id,
                            "name": call.name,
                            "count": repetition.consecutive_count,
                            "action": "warn",
                        },
                    )
                else:
                    result = await self._await_guarded(
                        self._tools.execute(call, context),
                        state,
                        deadline,
                    )
                result = replace(
                    result,
                    output=truncate_text(result.output, self._limits.max_tool_output_chars),
                )
                state.messages.append(ChatMessage.tool(result.to_message_content(), call.id))
                state.modified_files.update(result.modified_files)
                if result.workspace_changed:
                    state.workspace_version += 1
                state.publish(
                    "tool.completed",
                    {
                        "tool_call_id": call.id,
                        "name": call.name,
                        "status": result.status,
                    },
                )

        state.transition(SessionStatus.FAILED, reason=TerminationReason.MAX_ITERATIONS)

    @staticmethod
    def _check_boundary(state: SessionState, deadline: float) -> None:
        if state.cancellation_requested:
            raise _RuntimeCancelled
        if asyncio.get_running_loop().time() >= deadline:
            raise _RuntimeTimedOut

    async def _await_guarded(
        self,
        awaitable: Awaitable[T],
        state: SessionState,
        deadline: float,
    ) -> T:
        self._check_boundary(state, deadline)
        operation = asyncio.ensure_future(awaitable)
        cancellation = asyncio.create_task(state.cancel_event.wait())
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        done, _ = await asyncio.wait(
            {operation, cancellation},
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if cancellation in done and cancellation.result():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise _RuntimeCancelled
        cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)
        if operation not in done:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise _RuntimeTimedOut
        return operation.result()

    @staticmethod
    async def _approval_requested(state: SessionState, approval: object) -> None:
        state.transition(SessionStatus.WAITING_APPROVAL)
        state.publish(
            "approval.requested",
            {
                "approval_id": getattr(approval, "approval_id", ""),
                "tool_call_id": getattr(approval, "tool_call_id", ""),
                "command": getattr(approval, "command", ""),
                "workspace": str(getattr(approval, "workspace", state.workspace)),
                "reason": getattr(approval, "reason", ""),
            },
        )

    @staticmethod
    async def _approval_resolved(
        state: SessionState,
        approval: object,
        approved: bool,
    ) -> None:
        if state.status is SessionStatus.WAITING_APPROVAL:
            state.transition(SessionStatus.RUNNING)
        state.publish(
            "approval.resolved",
            {
                "approval_id": getattr(approval, "approval_id", ""),
                "approved": approved,
            },
        )
