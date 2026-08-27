"""FastAPI 应用工厂、依赖容器和路由。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agent.repository import InMemorySessionRepository, SessionNotFoundError
from app.agent.runtime import AgentRuntime
from app.agent.state import AgentEvent, SessionState, SessionStatus, TerminationReason
from app.config import inspect_model_configuration, load_model_settings
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.redaction import SecretRedactor
from app.safety.approval import ApprovalError, ApprovalService
from app.services import WorkspaceFileService
from app.tools.base import ToolContext
from app.tools.defaults import build_file_tool_registry
from app.tools.git_tools import GitDiffArguments, GitDiffTool
from app.tools.paths import WorkspaceError, WorkspaceErrorCode, validate_workspace

RuntimeFactory = Callable[[SessionState], AgentRuntime]
ConfigInspector = Callable[[], Any]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceRequest(StrictModel):
    path: str = Field(min_length=1)


class SessionRequest(StrictModel):
    workspace: str = Field(min_length=1)


class TaskRequest(StrictModel):
    task: str = Field(min_length=1)


class ApprovalRequest(StrictModel):
    approved: bool


def _default_runtime_factory(approval_service: ApprovalService) -> RuntimeFactory:
    def factory(state: SessionState) -> AgentRuntime:
        settings = load_model_settings()
        redactor = SecretRedactor([settings.api_key.get_secret_value()])
        provider = OpenAICompatibleProvider(settings)
        tools = build_file_tool_registry(
            approval_service=approval_service,
            redactor=redactor,
        )
        return AgentRuntime(
            provider,
            tools,
            system_prompt=(
                "你是本地 Coding Agent。先读取必要上下文，使用工具完成修改，"
                "并主动运行相关测试。所有工具路径必须相对于工作区。"
            ),
        )

    return factory


class AppServices:
    def __init__(
        self,
        *,
        repository: InMemorySessionRepository | None = None,
        approval_service: ApprovalService | None = None,
        runtime_factory: RuntimeFactory | None = None,
        config_inspector: ConfigInspector = inspect_model_configuration,
        max_concurrent_tasks: int = 2,
    ) -> None:
        if max_concurrent_tasks <= 0:
            raise ValueError("max_concurrent_tasks must be positive")
        self.repository = repository or InMemorySessionRepository()
        self.approval_service = approval_service or ApprovalService()
        self.runtime_factory = runtime_factory or _default_runtime_factory(self.approval_service)
        self.config_inspector = config_inspector
        self.max_concurrent_tasks = max_concurrent_tasks
        self._active: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def submit(self, state: SessionState, task_text: str) -> None:
        async with self._lock:
            if state.session_id in self._active or state.status is not SessionStatus.QUEUED:
                raise RuntimeError("会话已有任务或不能再次运行")
            if len(self._active) >= self.max_concurrent_tasks:
                raise OverflowError("已达同时运行任务上限")
            running = asyncio.create_task(self._run(state, task_text))
            self._active[state.session_id] = running

    async def _run(self, state: SessionState, task_text: str) -> None:
        try:
            runtime = self.runtime_factory(state)
            await runtime.run(state, task_text)
        except Exception:
            if not state.is_terminal:
                state.transition(SessionStatus.FAILED, reason=TerminationReason.INTERNAL_ERROR)
        finally:
            async with self._lock:
                self._active.pop(state.session_id, None)

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = tuple(self._active.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _event_dict(event: AgentEvent) -> dict[str, Any]:
    return {
        "session_id": event.session_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat(),
        "payload": dict(event.payload),
    }


async def _snapshot(state: SessionState, services: AppServices) -> dict[str, Any]:
    pending = await services.approval_service.list_pending(state.session_id)
    return {
        "session_id": state.session_id,
        "workspace": str(state.workspace),
        "status": state.status.value,
        "iteration": state.iteration,
        "termination_reason": (
            state.termination_reason.value if state.termination_reason is not None else None
        ),
        "final_answer": state.final_answer,
        "modified_files": sorted(state.modified_files),
        "workspace_version": state.workspace_version,
        "latest_sequence": state.events.latest_sequence,
        "pending_approvals": [
            {
                "approval_id": item.approval_id,
                "tool_call_id": item.tool_call_id,
                "command": item.command,
                "workspace": str(item.workspace),
                "reason": item.reason,
                "arguments": dict(item.arguments),
                "expires_at": item.expires_at.isoformat(),
            }
            for item in pending
        ],
    }


def _workspace_http_error(exc: WorkspaceError) -> HTTPException:
    status = 404 if exc.code is WorkspaceErrorCode.WORKSPACE_NOT_FOUND else 400
    return HTTPException(status_code=status, detail={"error": exc.code.value, "message": str(exc)})


async def session_event_stream(
    state: SessionState,
    services: AppServices,
    requested_sequence: int,
    *,
    heartbeat_seconds: float = 1.0,
) -> AsyncIterator[str]:
    last_sequence = requested_sequence
    earliest = state.events.earliest_sequence
    if earliest is not None and requested_sequence < earliest - 1:
        snapshot = await _snapshot(state, services)
        yield f"event: snapshot\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        last_sequence = earliest - 1
    while True:
        events = state.events.after(last_sequence)
        if events:
            for event in events:
                data = json.dumps(_event_dict(event), ensure_ascii=False)
                yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {data}\n\n"
                last_sequence = event.sequence
            if state.is_terminal and last_sequence >= state.events.latest_sequence:
                return
        elif state.is_terminal:
            return
        else:
            yield ": heartbeat\n\n"
            await asyncio.sleep(heartbeat_seconds)


def create_app(
    services: AppServices | None = None,
    *,
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173"),
) -> FastAPI:
    container = services or AppServices()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await container.shutdown()

    app = FastAPI(title="CodeAgent", version="0.1.0", lifespan=lifespan)
    app.state.services = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config/status")
    async def config_status() -> dict[str, Any]:
        status = container.config_inspector()
        return {"ready": status.ready, "summary": status.summary, "errors": status.errors}

    @app.post("/api/workspaces/validate")
    async def workspace_validate(body: WorkspaceRequest) -> dict[str, Any]:
        try:
            workspace = validate_workspace(body.path)
        except WorkspaceError as exc:
            raise _workspace_http_error(exc) from exc
        return {"valid": True, "path": str(workspace)}

    @app.post("/api/sessions", status_code=201)
    async def create_session(body: SessionRequest) -> dict[str, Any]:
        try:
            workspace = validate_workspace(body.workspace)
        except WorkspaceError as exc:
            raise _workspace_http_error(exc) from exc
        state = await container.repository.create(workspace)
        return await _snapshot(state, container)

    async def get_state(session_id: str) -> SessionState:
        try:
            return await container.repository.get(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.get("/api/sessions/{session_id}")
    async def session_snapshot(session_id: str) -> dict[str, Any]:
        return await _snapshot(await get_state(session_id), container)

    @app.post("/api/sessions/{session_id}/tasks", status_code=202)
    async def submit_task(session_id: str, body: TaskRequest) -> dict[str, Any]:
        state = await get_state(session_id)
        config = container.config_inspector()
        if not config.ready:
            raise HTTPException(status_code=503, detail={"error": "model_not_configured"})
        try:
            await container.submit(state, body.task.strip())
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return {"accepted": True, "session_id": session_id}

    @app.post("/api/sessions/{session_id}/cancel")
    async def cancel_task(session_id: str) -> dict[str, Any]:
        state = await get_state(session_id)
        if state.is_terminal:
            return await _snapshot(state, container)
        state.request_cancel()
        await container.approval_service.cancel_session(session_id)
        if state.status is SessionStatus.QUEUED:
            state.transition(SessionStatus.CANCELLED, reason=TerminationReason.CANCELLED)
        return await _snapshot(state, container)

    @app.post("/api/sessions/{session_id}/approvals/{approval_id}")
    async def resolve_approval(
        session_id: str,
        approval_id: str,
        body: ApprovalRequest,
    ) -> dict[str, Any]:
        state = await get_state(session_id)
        if state.status is not SessionStatus.WAITING_APPROVAL:
            raise HTTPException(status_code=409, detail="session is not waiting for approval")
        try:
            pending = await container.approval_service.get(approval_id)
            resolved = await container.approval_service.resolve(
                approval_id,
                session_id=session_id,
                tool_call_id=pending.tool_call_id,
                arguments=pending.arguments,
                approved=body.approved,
            )
        except ApprovalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"approval_id": resolved.approval_id, "status": resolved.status.value}

    @app.get("/api/sessions/{session_id}/files/tree")
    async def file_tree(
        session_id: str,
        path: str = ".",
        depth: int = Query(default=3, ge=0, le=10),
    ) -> dict[str, Any]:
        state = await get_state(session_id)
        service = WorkspaceFileService(state.workspace)
        try:
            entries, truncated = service.list_entries(path, max_depth=depth, max_entries=500)
        except WorkspaceError as exc:
            raise _workspace_http_error(exc) from exc
        return {
            "path": path,
            "entries": [entry.as_dict() for entry in entries],
            "truncated": truncated,
        }

    @app.get("/api/sessions/{session_id}/files/content")
    async def file_content(session_id: str, path: str) -> dict[str, Any]:
        state = await get_state(session_id)
        service = WorkspaceFileService(state.workspace)
        try:
            text = service.read_text(path)
        except WorkspaceError as exc:
            raise _workspace_http_error(exc) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": path, "content": text, "total_lines": len(text.splitlines())}

    @app.get("/api/sessions/{session_id}/diff")
    async def task_diff(session_id: str, path: str = ".") -> dict[str, Any]:
        state = await get_state(session_id)
        context = ToolContext("api", state.workspace, lambda: False)
        try:
            result = await GitDiffTool().execute(GitDiffArguments(path=path), context)
        except WorkspaceError as exc:
            raise _workspace_http_error(exc) from exc
        if result.status == "error":
            raise HTTPException(status_code=400, detail=result.summary)
        return {"path": path, "diff": result.output, "metadata": dict(result.metadata)}

    @app.get("/api/sessions/{session_id}/events")
    async def session_events(
        session_id: str,
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        state = await get_state(session_id)
        query_sequence = request.query_params.get("last_event_id")
        raw_sequence = last_event_id or query_sequence or "0"
        try:
            sequence = max(0, int(raw_sequence))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid Last-Event-ID") from exc
        return StreamingResponse(
            session_event_stream(state, container, sequence),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
