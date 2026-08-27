"""受策略保护的异步 shell 命令执行。"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from dataclasses import dataclass
from time import monotonic

from pydantic import Field

from app.agent.context import truncate_text
from app.safety import CommandRisk, classify_command
from app.safety.approval import ApprovalError, ApprovalService
from app.tools.base import ToolArguments, ToolContext, ToolResult


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    cancelled: bool = False


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=0.5)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


async def execute_command(
    command: str,
    context: ToolContext,
    *,
    timeout_seconds: float,
) -> CommandOutcome:
    started = monotonic()
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=context.workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    communication = asyncio.create_task(process.communicate())
    deadline = monotonic() + timeout_seconds
    timed_out = False
    cancelled = False
    try:
        while not communication.done():
            if context.cancellation_requested():
                cancelled = True
                await _terminate_process_group(process)
                break
            remaining = deadline - monotonic()
            if remaining <= 0:
                timed_out = True
                await _terminate_process_group(process)
                break
            await asyncio.wait({communication}, timeout=min(0.05, remaining))
        stdout_bytes, stderr_bytes = await communication
    except BaseException:
        await _terminate_process_group(process)
        communication.cancel()
        await asyncio.gather(communication, return_exceptions=True)
        raise
    return CommandOutcome(
        exit_code=process.returncode,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        duration_seconds=monotonic() - started,
        timed_out=timed_out,
        cancelled=cancelled,
    )


class RunCommandArguments(ToolArguments):
    command: str = Field(min_length=1)
    timeout_seconds: float = Field(default=60.0, gt=0, le=120)


class RunCommandTool:
    name = "run_command"
    description = "在工作区中执行受控 shell 命令，返回退出码、stdout、stderr 和耗时。"
    arguments_model = RunCommandArguments

    def __init__(self, approval_service: ApprovalService | None = None) -> None:
        self._approval_service = approval_service

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        parsed = RunCommandArguments.model_validate(arguments)
        decision = classify_command(parsed.command)
        if decision.risk is CommandRisk.DENY:
            return ToolResult.error(
                "command_denied",
                decision.reason,
                metadata={"risk": decision.risk.value},
            )
        if decision.risk is CommandRisk.APPROVAL_REQUIRED:
            if self._approval_service is None:
                return ToolResult.error(
                    "approval_required",
                    decision.reason,
                    metadata={"risk": decision.risk.value, "command": parsed.command},
                )
            arguments_payload = parsed.model_dump(mode="json")
            approval = await self._approval_service.request(
                session_id=context.session_id,
                tool_call_id=context.tool_call_id,
                arguments=arguments_payload,
                command=parsed.command,
                workspace=context.workspace,
                reason=decision.reason,
            )
            if context.on_approval_requested is not None:
                await context.on_approval_requested(approval)
            try:
                approved = await self._approval_service.wait(
                    approval.approval_id,
                    cancellation_requested=context.cancellation_requested,
                )
            except asyncio.CancelledError:
                await self._approval_service.cancel_session(context.session_id)
                raise
            except ApprovalError as exc:
                return ToolResult.error("approval_invalid", str(exc))
            if context.on_approval_resolved is not None:
                await context.on_approval_resolved(approval, approved)
            if not approved:
                return ToolResult.error("approval_denied", "用户拒绝执行命令")

        outcome = await execute_command(
            parsed.command,
            context,
            timeout_seconds=parsed.timeout_seconds,
        )
        payload = {
            "command": parsed.command,
            "exit_code": outcome.exit_code,
            "stdout": outcome.stdout,
            "stderr": outcome.stderr,
            "duration_seconds": round(outcome.duration_seconds, 3),
            "timed_out": outcome.timed_out,
            "cancelled": outcome.cancelled,
        }
        output = truncate_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            context.output_limit,
        )
        metadata = {
            "risk": decision.risk.value,
            "exit_code": outcome.exit_code,
            "duration_seconds": outcome.duration_seconds,
            "timed_out": outcome.timed_out,
            "cancelled": outcome.cancelled,
        }
        if outcome.cancelled:
            return ToolResult.error("cancelled", "命令已取消", output=output, metadata=metadata)
        if outcome.timed_out:
            return ToolResult.error("timeout", "命令执行超时", output=output, metadata=metadata)
        if outcome.exit_code != 0:
            return ToolResult.error(
                "command_failed",
                f"命令以退出码 {outcome.exit_code} 结束",
                output=output,
                metadata=metadata,
            )
        return ToolResult.success("命令执行成功", output=output, metadata=metadata)
