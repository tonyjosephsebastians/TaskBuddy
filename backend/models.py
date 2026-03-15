from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolStep:
    tool_name: str
    params: dict[str, Any]


@dataclass
class ParsedTask:
    original_text: str
    sanitized_text: str
    steps: list[ToolStep] = field(default_factory=list)
    output_transform: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    summary: str
    data: dict[str, Any]
    trace_message: str
    status: str = "completed"


@dataclass
class TraceStep:
    step_number: int
    phase: str
    status: str
    message: str
    tool_name: str | None = None
    payload: dict[str, Any] | None = None


@dataclass
class TurnExecution:
    turn_id: str
    task_text: str
    sanitized_text: str
    status: str
    final_output: str
    output_data: dict[str, Any]
    tools_used: list[str]
    execution_steps: list[TraceStep]
    timestamp: str
    trace_id: str


@dataclass
class ThreadSummary:
    thread_id: str
    title: str
    last_message_preview: str
    updated_at: str


@dataclass
class ThreadDetail:
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    turns: list[TurnExecution] = field(default_factory=list)


@dataclass
class UserAccount:
    user_id: str
    username: str
    role: str
    created_at: str
    password_hash: str | None = None
    password_salt: str | None = None
