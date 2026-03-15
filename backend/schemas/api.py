from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TaskCreateRequest(BaseModel):
    task_text: str = Field(..., min_length=1)
    client_request_id: str | None = None


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    role: str


class ExecutionStepResponse(BaseModel):
    step_number: int
    phase: str
    status: str
    message: str
    tool_name: str | None = None
    payload: dict[str, Any] | None = None


class TurnResponse(BaseModel):
    turn_id: str
    task_text: str
    status: str
    final_output: str
    output_data: dict[str, Any]
    tools_used: list[str]
    execution_steps: list[ExecutionStepResponse]
    timestamp: str
    trace_id: str


class ThreadSummaryResponse(BaseModel):
    thread_id: str
    title: str
    last_message_preview: str
    updated_at: str


class ThreadDetailResponse(BaseModel):
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    turns: list[TurnResponse]


class AuthMeResponse(BaseModel):
    user_id: str
    username: str
    role: str


class UserSummaryResponse(BaseModel):
    user_id: str
    username: str
    role: str
    created_at: str


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    trace_id: str
    details: dict[str, Any] = Field(default_factory=dict)
