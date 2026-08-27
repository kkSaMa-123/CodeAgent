from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.safety.approval import ApprovalError, ApprovalService, ApprovalStatus, arguments_digest


def test_arguments_digest_is_order_independent() -> None:
    assert arguments_digest({"command": "rm x", "timeout": 2}) == arguments_digest(
        {"timeout": 2, "command": "rm x"}
    )


def test_approval_can_resume_async_waiter_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = ApprovalService()
        arguments = {"command": "rm generated.txt", "timeout_seconds": 60.0}
        approval = await service.request(
            session_id="session",
            tool_call_id="call",
            arguments=arguments,
            command="rm generated.txt",
            workspace=tmp_path,
            reason="delete",
        )
        waiting = asyncio.create_task(
            service.wait(approval.approval_id, cancellation_requested=lambda: False)
        )
        resolved = await service.resolve(
            approval.approval_id,
            session_id="session",
            tool_call_id="call",
            arguments=arguments,
            approved=True,
        )

        assert await waiting is True
        assert resolved.status is ApprovalStatus.APPROVED
        with pytest.raises(ApprovalError):
            await service.resolve(
                approval.approval_id,
                session_id="session",
                tool_call_id="call",
                arguments=arguments,
                approved=True,
            )

    asyncio.run(scenario())


def test_rejects_cross_session_and_changed_arguments(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = ApprovalService()
        original = {"command": "rm a"}
        approval = await service.request(
            session_id="owner",
            tool_call_id="call",
            arguments=original,
            command="rm a",
            workspace=tmp_path,
            reason="delete",
        )
        with pytest.raises(ApprovalError):
            await service.resolve(
                approval.approval_id,
                session_id="other",
                tool_call_id="call",
                arguments=original,
                approved=True,
            )
        with pytest.raises(ApprovalError):
            await service.resolve(
                approval.approval_id,
                session_id="owner",
                tool_call_id="call",
                arguments={"command": "rm b"},
                approved=True,
            )

    asyncio.run(scenario())


def test_expired_approval_cannot_be_consumed(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = ApprovalService(ttl_seconds=0.01)
        arguments = {"command": "rm a"}
        approval = await service.request(
            session_id="session",
            tool_call_id="call",
            arguments=arguments,
            command="rm a",
            workspace=tmp_path,
            reason="delete",
        )
        await asyncio.sleep(0.02)
        with pytest.raises(ApprovalError):
            await service.resolve(
                approval.approval_id,
                session_id="session",
                tool_call_id="call",
                arguments=arguments,
                approved=True,
            )
        assert (await service.get(approval.approval_id)).status is ApprovalStatus.EXPIRED

    asyncio.run(scenario())

