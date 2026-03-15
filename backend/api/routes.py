from __future__ import annotations

from dataclasses import asdict
import json

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from backend.agent.controller import AgentController
from backend.config import DEMO_PACING_ENABLED, JWT_EXPIRATION_HOURS, ROLE_ADMIN, SESSION_COOKIE_NAME
from backend.errors import AppError
from backend.models import ThreadDetail, TurnExecution, UserAccount
from backend.persistence.repository import TaskRepository
from backend.schemas.api import (
    AuthMeResponse,
    LoginRequest,
    TaskCreateRequest,
    ThreadDetailResponse,
    ThreadSummaryResponse,
    TurnResponse,
    UserCreateRequest,
    UserSummaryResponse,
)
from backend.security import create_access_token, decode_access_token, verify_password


router = APIRouter()


def get_repository(request: Request) -> TaskRepository:
    return request.app.state.repository


def get_controller(request: Request) -> AgentController:
    return request.app.state.controller


def _to_turn_response(execution: TurnExecution) -> TurnResponse:
    return TurnResponse(
        turn_id=execution.turn_id,
        task_text=execution.task_text,
        status=execution.status,
        final_output=execution.final_output,
        output_data=execution.output_data,
        tools_used=execution.tools_used,
        execution_steps=[asdict(step) for step in execution.execution_steps],
        timestamp=execution.timestamp,
        trace_id=execution.trace_id,
    )


def _to_thread_detail_response(thread: ThreadDetail) -> ThreadDetailResponse:
    return ThreadDetailResponse(
        thread_id=thread.thread_id,
        title=thread.title,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        turns=[_to_turn_response(turn) for turn in thread.turns],
    )


def _to_auth_response(user: UserAccount) -> AuthMeResponse:
    return AuthMeResponse(user_id=user.user_id, username=user.username, role=user.role)


def _to_user_summary(user: UserAccount) -> UserSummaryResponse:
    return UserSummaryResponse(
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        created_at=user.created_at,
    )


def _format_sse(event_name: str, payload: dict[str, object]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def _stream_error_payload(error: AppError, trace_id: str) -> dict[str, object]:
    return {
        "type": "failed",
        "error_code": error.error_code,
        "message": error.message,
        "details": error.details,
        "status_code": error.status_code,
        "trace_id": trace_id,
    }


def get_current_user(request: Request, repository: TaskRepository = Depends(get_repository)) -> UserAccount:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise AppError("AUTH_REQUIRED", "Authentication is required.", 401)
    payload = decode_access_token(token)
    user = repository.get_user_by_id(payload["sub"])
    if user is None:
        raise AppError("AUTH_REQUIRED", "Authentication is required.", 401)
    return user


def require_admin(user: UserAccount = Depends(get_current_user)) -> UserAccount:
    if user.role != ROLE_ADMIN:
        raise AppError("FORBIDDEN", "Administrator access is required.", 403)
    return user


@router.post("/auth/login", response_model=AuthMeResponse)
def login(payload: LoginRequest, response: Response, repository: TaskRepository = Depends(get_repository)) -> AuthMeResponse:
    user = repository.get_user_by_username(payload.username)
    if user is None or not user.password_hash or not user.password_salt:
        raise AppError("AUTH_INVALID_CREDENTIALS", "Invalid username or password.", 401)
    if not verify_password(payload.password, user.password_hash, user.password_salt):
        raise AppError("AUTH_INVALID_CREDENTIALS", "Invalid username or password.", 401)

    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_access_token(user),
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=JWT_EXPIRATION_HOURS * 3600,
        path="/",
    )
    return _to_auth_response(user)


@router.post("/auth/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/auth/me", response_model=AuthMeResponse)
def auth_me(user: UserAccount = Depends(get_current_user)) -> AuthMeResponse:
    return _to_auth_response(user)


@router.get("/threads", response_model=list[ThreadSummaryResponse])
def list_threads(
    search: str = "",
    user: UserAccount = Depends(get_current_user),
    repository: TaskRepository = Depends(get_repository),
) -> list[ThreadSummaryResponse]:
    threads = repository.list_threads(user.user_id, search=search)
    return [
        ThreadSummaryResponse(
            thread_id=thread.thread_id,
            title=thread.title,
            last_message_preview=thread.last_message_preview,
            updated_at=thread.updated_at,
        )
        for thread in threads
    ]


@router.post("/threads", response_model=ThreadDetailResponse)
def create_thread(
    user: UserAccount = Depends(get_current_user),
    repository: TaskRepository = Depends(get_repository),
) -> ThreadDetailResponse:
    thread = repository.create_thread(user.user_id)
    return _to_thread_detail_response(thread)


@router.get("/threads/{thread_id}", response_model=ThreadDetailResponse)
def get_thread(
    thread_id: str,
    user: UserAccount = Depends(get_current_user),
    repository: TaskRepository = Depends(get_repository),
) -> ThreadDetailResponse:
    thread = repository.get_thread(thread_id, user.user_id)
    if thread is None:
        raise AppError("THREAD_NOT_FOUND", "Thread not found.", 404, {"thread_id": thread_id})
    return _to_thread_detail_response(thread)


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(
    thread_id: str,
    user: UserAccount = Depends(get_current_user),
    repository: TaskRepository = Depends(get_repository),
) -> Response:
    deleted = repository.delete_thread(thread_id, user.user_id)
    if not deleted:
        raise AppError("THREAD_NOT_FOUND", "Thread not found.", 404, {"thread_id": thread_id})
    return Response(status_code=204)


@router.post("/threads/{thread_id}/tasks", response_model=TurnResponse)
def create_thread_task(
    thread_id: str,
    payload: TaskCreateRequest,
    request: Request,
    user: UserAccount = Depends(get_current_user),
    repository: TaskRepository = Depends(get_repository),
    controller: AgentController = Depends(get_controller),
) -> TurnResponse:
    repository.ensure_thread_flow_capacity(thread_id, user.user_id)
    execution = controller.execute_task(payload.task_text, trace_id=request.state.trace_id)
    repository.save_turn(thread_id, user.user_id, execution)
    return _to_turn_response(execution)


@router.post("/threads/{thread_id}/tasks/stream")
def create_thread_task_stream(
    thread_id: str,
    payload: TaskCreateRequest,
    request: Request,
    user: UserAccount = Depends(get_current_user),
    repository: TaskRepository = Depends(get_repository),
    controller: AgentController = Depends(get_controller),
) -> StreamingResponse:
    trace_id = request.state.trace_id
    repository.ensure_thread_flow_capacity(thread_id, user.user_id)

    def event_stream():
        stream = controller.execute_task_stream(
            payload.task_text,
            trace_id=trace_id,
            pacing_enabled=DEMO_PACING_ENABLED,
        )
        try:
            while True:
                event = next(stream)
                yield _format_sse(str(event["type"]), event)
        except StopIteration as stopped:
            execution = stopped.value
            try:
                repository.save_turn(thread_id, user.user_id, execution)
                thread = repository.get_thread(thread_id, user.user_id)
                if thread is None:
                    raise AppError("THREAD_NOT_FOUND", "Thread not found.", 404, {"thread_id": thread_id})
                yield _format_sse(
                    "completed",
                    {
                        "type": "completed",
                        "trace_id": execution.trace_id,
                        "timestamp": execution.timestamp,
                        "turn": _to_turn_response(execution).model_dump(),
                        "thread": _to_thread_detail_response(thread).model_dump(),
                    },
                )
            except AppError as error:
                yield _format_sse("failed", _stream_error_payload(error, trace_id))
        except AppError as error:
            yield _format_sse("failed", _stream_error_payload(error, trace_id))
        except Exception:
            yield _format_sse(
                "failed",
                {
                    "type": "failed",
                    "error_code": "STREAM_EXECUTION_FAILED",
                    "message": "Streaming execution failed unexpectedly.",
                    "details": {},
                    "status_code": 500,
                    "trace_id": trace_id,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/admin/users", response_model=list[UserSummaryResponse])
def list_users(
    _: UserAccount = Depends(require_admin),
    repository: TaskRepository = Depends(get_repository),
) -> list[UserSummaryResponse]:
    return [_to_user_summary(user) for user in repository.list_users()]


@router.post("/admin/users", response_model=UserSummaryResponse)
def create_user(
    payload: UserCreateRequest,
    _: UserAccount = Depends(require_admin),
    repository: TaskRepository = Depends(get_repository),
) -> UserSummaryResponse:
    user = repository.create_user(payload.username, payload.password, payload.role)
    return _to_user_summary(user)


@router.delete("/admin/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    admin: UserAccount = Depends(require_admin),
    repository: TaskRepository = Depends(get_repository),
) -> Response:
    if user_id == admin.user_id:
        raise AppError("CANNOT_DELETE_CURRENT_USER", "Sign out before removing the current admin account.", 422)

    deleted = repository.delete_user(user_id)
    if not deleted:
        raise AppError("USER_NOT_FOUND", "User not found.", 404, {"user_id": user_id})
    return Response(status_code=204)
