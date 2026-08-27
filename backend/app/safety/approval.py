"""与会话、调用和参数摘要绑定的一次性审批。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalError(RuntimeError):
    pass


def arguments_digest(arguments: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(arguments),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PendingApproval:
    approval_id: str
    session_id: str
    tool_call_id: str
    arguments_digest: str
    arguments: Mapping[str, Any]
    command: str
    workspace: Path
    reason: str
    status: ApprovalStatus
    created_at: datetime
    expires_at: datetime


class ApprovalService:
    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = ttl_seconds
        self._approvals: dict[str, PendingApproval] = {}
        self._waiters: dict[str, asyncio.Future[bool]] = {}
        self._lock = asyncio.Lock()

    async def request(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        arguments: Mapping[str, Any],
        command: str,
        workspace: Path,
        reason: str,
    ) -> PendingApproval:
        now = datetime.now(UTC)
        approval = PendingApproval(
            approval_id=str(uuid4()),
            session_id=session_id,
            tool_call_id=tool_call_id,
            arguments_digest=arguments_digest(arguments),
            arguments=MappingProxyType(dict(arguments)),
            command=command,
            workspace=workspace,
            reason=reason,
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
        )
        async with self._lock:
            self._approvals[approval.approval_id] = approval
            self._waiters[approval.approval_id] = asyncio.get_running_loop().create_future()
        return approval

    async def get(self, approval_id: str) -> PendingApproval:
        async with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None:
                raise ApprovalError("审批请求不存在")
            return approval

    async def list_pending(self, session_id: str | None = None) -> tuple[PendingApproval, ...]:
        async with self._lock:
            return tuple(
                approval
                for approval in self._approvals.values()
                if approval.status is ApprovalStatus.PENDING
                and (session_id is None or approval.session_id == session_id)
            )

    async def resolve(
        self,
        approval_id: str,
        *,
        session_id: str,
        tool_call_id: str,
        arguments: Mapping[str, Any],
        approved: bool,
    ) -> PendingApproval:
        async with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None:
                raise ApprovalError("审批请求不存在")
            if approval.session_id != session_id or approval.tool_call_id != tool_call_id:
                raise ApprovalError("审批与会话或工具调用不匹配")
            if approval.arguments_digest != arguments_digest(arguments):
                raise ApprovalError("审批参数摘要不匹配")
            if approval.status is not ApprovalStatus.PENDING:
                raise ApprovalError("审批已失效或被消费")
            if datetime.now(UTC) >= approval.expires_at:
                expired = replace(approval, status=ApprovalStatus.EXPIRED)
                self._approvals[approval_id] = expired
                waiter = self._waiters[approval_id]
                if not waiter.done():
                    waiter.set_exception(ApprovalError("审批已过期"))
                raise ApprovalError("审批已过期")
            resolved = replace(
                approval,
                status=ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED,
            )
            self._approvals[approval_id] = resolved
            waiter = self._waiters[approval_id]
            if not waiter.done():
                waiter.set_result(approved)
            return resolved

    async def wait(
        self,
        approval_id: str,
        *,
        cancellation_requested: Callable[[], bool],
    ) -> bool:
        approval = await self.get(approval_id)
        async with self._lock:
            waiter = self._waiters[approval_id]
        while not waiter.done():
            if cancellation_requested():
                await self.cancel_session(approval.session_id)
                raise ApprovalError("任务已取消")
            if datetime.now(UTC) >= approval.expires_at:
                async with self._lock:
                    current = self._approvals[approval_id]
                    if current.status is ApprovalStatus.PENDING:
                        self._approvals[approval_id] = replace(
                            current,
                            status=ApprovalStatus.EXPIRED,
                        )
                raise ApprovalError("审批已过期")
            await asyncio.sleep(0.05)
        return waiter.result()

    async def cancel_session(self, session_id: str) -> None:
        async with self._lock:
            for approval_id, approval in tuple(self._approvals.items()):
                if (
                    approval.session_id != session_id
                    or approval.status is not ApprovalStatus.PENDING
                ):
                    continue
                self._approvals[approval_id] = replace(
                    approval,
                    status=ApprovalStatus.CANCELLED,
                )
                waiter = self._waiters[approval_id]
                if not waiter.done():
                    waiter.set_exception(ApprovalError("任务已取消"))
