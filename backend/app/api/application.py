"""项目、对话和运行资源的 FastAPI 应用。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agent.change_tracker import RunChangeTracker
from app.agent.context import ConversationContext
from app.agent.runtime import AgentRuntime
from app.agent.state import EventBuffer, RunState, SessionStatus, TerminationReason
from app.config import database_path, inspect_model_configuration, load_model_settings
from app.persistence import (
    ConflictError,
    NotFoundError,
    SQLiteRepository,
    public_dict,
)
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.redaction import SecretRedactor
from app.safety.approval import ApprovalError, ApprovalService
from app.services import WorkspaceFileService
from app.tools.base import ToolContext
from app.tools.defaults import build_file_tool_registry
from app.tools.git_tools import GitDiffArguments, GitDiffTool
from app.tools.paths import WorkspaceError, WorkspaceErrorCode, validate_workspace

RuntimeFactory = Callable[[RunState], AgentRuntime]
ConfigInspector = Callable[[], Any]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceRequest(StrictModel):
    path: str = Field(min_length=1)


class ProjectRequest(StrictModel):
    workspace: str = Field(min_length=1)
    name: str | None = None


class NameRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)


class ConversationRequest(StrictModel):
    title: str = Field(default="新对话", max_length=120)


class TitleRequest(StrictModel):
    title: str = Field(min_length=1, max_length=120)


class TaskRequest(StrictModel):
    task: str = Field(min_length=1)


class ApprovalRequest(StrictModel):
    approved: bool


def _default_runtime_factory(approval_service: ApprovalService) -> RuntimeFactory:
    def factory(state: RunState) -> AgentRuntime:
        settings = load_model_settings()
        redactor = SecretRedactor([settings.api_key.get_secret_value()])
        return AgentRuntime(
            OpenAICompatibleProvider(settings),
            build_file_tool_registry(approval_service=approval_service, redactor=redactor),
            system_prompt=(
                "你是本地 Coding Agent。先读取必要上下文，使用工具完成修改，并主动运行相关测试。"
                "所有工具路径必须相对于工作区。"
            ),
        )

    return factory


class AppServices:
    def __init__(
        self,
        *,
        repository: SQLiteRepository | None = None,
        approval_service: ApprovalService | None = None,
        runtime_factory: RuntimeFactory | None = None,
        config_inspector: ConfigInspector = inspect_model_configuration,
        max_concurrent_tasks: int = 2,
    ) -> None:
        if max_concurrent_tasks <= 0:
            raise ValueError("max_concurrent_tasks must be positive")
        self.repository = repository or SQLiteRepository(database_path())
        self.approval_service = approval_service or ApprovalService()
        self.runtime_factory = runtime_factory or _default_runtime_factory(self.approval_service)
        self.config_inspector = config_inspector
        self.max_concurrent_tasks = max_concurrent_tasks
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._states: dict[str, RunState] = {}
        self._lock = asyncio.Lock()

    async def start(self, run_id: str, task_text: str) -> RunState:
        run = self.repository.get_run(run_id)
        async with self._lock:
            if run_id in self._tasks:
                raise ConflictError("运行已经启动")
            if len(self._tasks) >= self.max_concurrent_tasks:
                raise OverflowError("已达同时运行任务上限")
            history = self.repository.semantic_messages(
                run["conversation_id"], exclude_run_id=run_id
            )
            state = RunState(
                session_id=run_id,
                project_id=run["project_id"],
                conversation_id=run["conversation_id"],
                workspace=Path(run["workspace"]),
                messages=list(ConversationContext().build(history)),
                events=EventBuffer(session_id=run_id, on_publish=self.repository.append_event),
            )
            self._states[run_id] = state
            self._tasks[run_id] = asyncio.create_task(self._run(state, task_text))
            return state

    async def _run(self, state: RunState, task_text: str) -> None:
        tracker = RunChangeTracker(state.workspace)
        tracker.start()
        try:
            await self.runtime_factory(state).run(state, task_text)
        except Exception:
            if not state.is_terminal:
                state.transition(SessionStatus.FAILED, reason=TerminationReason.INTERNAL_ERROR)
        finally:
            try:
                self.repository.save_changes(state.run_id, tracker.finish())
                self.repository.finish_run(state)
            finally:
                async with self._lock:
                    self._tasks.pop(state.run_id, None)

    def state(self, run_id: str) -> RunState | None:
        return self._states.get(run_id)

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.repository.close()


def _workspace_http_error(exc: WorkspaceError) -> HTTPException:
    status = 404 if exc.code is WorkspaceErrorCode.WORKSPACE_NOT_FOUND else 400
    return HTTPException(status_code=status, detail={"error": exc.code.value, "message": str(exc)})


def _repo_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _run_snapshot(run: dict[str, Any], state: RunState | None = None) -> dict[str, Any]:
    result = dict(run)
    if state:
        result.update(
            status=state.status.value,
            termination_reason=state.termination_reason.value if state.termination_reason else None,
            final_answer=state.final_answer,
            iteration=state.iteration,
            modified_files=sorted(state.modified_files),
            latest_sequence=state.events.latest_sequence,
        )
    return result


async def run_event_stream(
    run_id: str, services: AppServices, requested_sequence: int, heartbeat_seconds: float = 1.0
) -> AsyncIterator[str]:
    last = requested_sequence
    while True:
        state = services.state(run_id)
        events = services.repository.list_events(run_id, last)
        for event in events:
            data = {"run_id": run_id, **event}
            encoded = json.dumps(data, ensure_ascii=False)
            yield f"id: {event['sequence']}\nevent: {event['event_type']}\ndata: {encoded}\n\n"
            last = event["sequence"]
        run = services.repository.get_run(run_id)
        status = state.status.value if state else run["status"]
        if status in {"completed", "failed", "cancelled"} and not services.repository.list_events(
            run_id, last
        ):
            return
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
        container.repository.recover_interrupted_runs()
        yield
        await container.shutdown()

    app = FastAPI(title="CodeAgent", version="0.2.0", lifespan=lifespan)
    app.state.services = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
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

    @app.get("/api/projects")
    async def projects() -> list[dict[str, Any]]:
        return [public_dict(item) for item in container.repository.list_projects()]

    @app.post("/api/projects", status_code=201)
    async def create_project(body: ProjectRequest) -> dict[str, Any]:
        try:
            return public_dict(container.repository.register_project(body.workspace, body.name))
        except (WorkspaceError, ValueError) as exc:
            if isinstance(exc, WorkspaceError):
                raise _workspace_http_error(exc) from exc
            raise _repo_http_error(exc) from exc

    @app.get("/api/projects/{project_id}")
    async def project(project_id: str) -> dict[str, Any]:
        try:
            return public_dict(container.repository.get_project(project_id, touch=True))
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc

    @app.patch("/api/projects/{project_id}")
    async def rename_project(project_id: str, body: NameRequest) -> dict[str, Any]:
        try:
            return public_dict(container.repository.rename_project(project_id, body.name))
        except (NotFoundError, ValueError) as exc:
            raise _repo_http_error(exc) from exc

    @app.delete("/api/projects/{project_id}", status_code=204)
    async def delete_project(project_id: str) -> Response:
        try:
            container.repository.delete_project(project_id)
        except (NotFoundError, ConflictError) as exc:
            raise _repo_http_error(exc) from exc
        return Response(status_code=204)

    @app.get("/api/projects/{project_id}/conversations")
    async def conversations(project_id: str) -> list[dict[str, Any]]:
        try:
            return [
                public_dict(item) for item in container.repository.list_conversations(project_id)
            ]
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc

    @app.post("/api/projects/{project_id}/conversations", status_code=201)
    async def create_conversation(project_id: str, body: ConversationRequest) -> dict[str, Any]:
        try:
            return public_dict(container.repository.create_conversation(project_id, body.title))
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc

    @app.patch("/api/conversations/{conversation_id}")
    async def rename_conversation(conversation_id: str, body: TitleRequest) -> dict[str, Any]:
        try:
            return public_dict(
                container.repository.rename_conversation(conversation_id, body.title)
            )
        except (NotFoundError, ValueError) as exc:
            raise _repo_http_error(exc) from exc

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(conversation_id: str) -> Response:
        try:
            container.repository.delete_conversation(conversation_id)
        except (NotFoundError, ConflictError) as exc:
            raise _repo_http_error(exc) from exc
        return Response(status_code=204)

    @app.get("/api/conversations/{conversation_id}/messages")
    async def messages(conversation_id: str) -> list[dict[str, Any]]:
        try:
            return container.repository.list_messages(conversation_id)
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc

    @app.get("/api/conversations/{conversation_id}/runs")
    async def runs(conversation_id: str) -> list[dict[str, Any]]:
        try:
            return container.repository.list_runs(conversation_id)
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc

    @app.post("/api/conversations/{conversation_id}/runs", status_code=202)
    async def create_run(conversation_id: str, body: TaskRequest) -> dict[str, Any]:
        config = container.config_inspector()
        if not config.ready:
            raise HTTPException(status_code=503, detail={"error": "model_not_configured"})
        try:
            run = container.repository.create_run(conversation_id, body.task)
            await container.start(run["id"], body.task.strip())
            return _run_snapshot(run, container.state(run["id"]))
        except OverflowError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except (NotFoundError, ConflictError, ValueError, WorkspaceError) as exc:
            raise _repo_http_error(exc) from exc

    @app.get("/api/runs/{run_id}")
    async def run_snapshot(run_id: str) -> dict[str, Any]:
        try:
            return _run_snapshot(container.repository.get_run(run_id), container.state(run_id))
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        try:
            run = container.repository.get_run(run_id)
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc
        state = container.state(run_id)
        if state and not state.is_terminal:
            state.request_cancel()
            await container.approval_service.cancel_session(run_id)
        return _run_snapshot(run, state)

    @app.post("/api/runs/{run_id}/approvals/{approval_id}")
    async def resolve_approval(
        run_id: str, approval_id: str, body: ApprovalRequest
    ) -> dict[str, Any]:
        state = container.state(run_id)
        if not state or state.status is not SessionStatus.WAITING_APPROVAL:
            raise HTTPException(status_code=409, detail="run is not waiting for approval")
        try:
            pending = await container.approval_service.get(approval_id)
            resolved = await container.approval_service.resolve(
                approval_id,
                session_id=run_id,
                tool_call_id=pending.tool_call_id,
                arguments=pending.arguments,
                approved=body.approved,
            )
        except ApprovalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"approval_id": resolved.approval_id, "status": resolved.status.value}

    def workspace_for_project(project_id: str) -> Path:
        try:
            project_value = container.repository.get_project(project_id)
            return validate_workspace(project_value.workspace)
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_http_error(exc) from exc

    @app.get("/api/projects/{project_id}/files/tree")
    async def file_tree(
        project_id: str, path: str = ".", depth: int = Query(3, ge=0, le=10)
    ) -> dict[str, Any]:
        try:
            entries, truncated = WorkspaceFileService(
                workspace_for_project(project_id)
            ).list_entries(path, max_depth=depth, max_entries=500)
        except WorkspaceError as exc:
            raise _workspace_http_error(exc) from exc
        return {
            "path": path,
            "entries": [item.as_dict() for item in entries],
            "truncated": truncated,
        }

    @app.get("/api/projects/{project_id}/files/content")
    async def file_content(project_id: str, path: str) -> dict[str, Any]:
        try:
            text = WorkspaceFileService(workspace_for_project(project_id)).read_text(path)
        except WorkspaceError as exc:
            raise _workspace_http_error(exc) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "path": path,
            "content": text,
            "total_lines": len(text.splitlines()),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        }

    @app.get("/api/runs/{run_id}/diff")
    async def current_diff(run_id: str, path: str = ".") -> dict[str, Any]:
        try:
            run = container.repository.get_run(run_id)
            result = await GitDiffTool().execute(
                GitDiffArguments(path=path),
                ToolContext("api", Path(run["workspace"]), lambda: False),
            )
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc
        if result.status == "error":
            raise HTTPException(status_code=400, detail=result.summary)
        return {"path": path, "diff": result.output, "metadata": dict(result.metadata)}

    @app.get("/api/runs/{run_id}/changes")
    async def changes(run_id: str) -> list[dict[str, Any]]:
        try:
            return container.repository.list_changes(run_id)
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc

    @app.get("/api/runs/{run_id}/changes/{change_id}")
    async def change(run_id: str, change_id: str) -> dict[str, Any]:
        try:
            return container.repository.get_change(run_id, change_id)
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc

    @app.get("/api/runs/{run_id}/changes/{change_id}/preview")
    async def change_preview(run_id: str, change_id: str) -> dict[str, Any]:
        try:
            item = container.repository.get_change(run_id, change_id)
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc
        return {
            key: item[key]
            for key in (
                "id",
                "path",
                "old_path",
                "change_type",
                "preview",
                "preview_kind",
                "after_hash",
            )
        }

    @app.get("/api/runs/{run_id}/events")
    async def run_events(
        run_id: str,
        request: Request,
        last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            container.repository.get_run(run_id)
            raw = last_event_id or request.query_params.get("last_event_id") or "0"
            sequence = max(0, int(raw))
        except NotFoundError as exc:
            raise _repo_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid Last-Event-ID") from exc
        return StreamingResponse(
            run_event_stream(run_id, container, sequence),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
