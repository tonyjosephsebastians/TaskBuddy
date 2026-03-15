from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from time import sleep
from typing import Any, Generator
from uuid import uuid4

from backend.agent.interpreter import TaskInterpreter
from backend.agent.state_graph import TaskExecutionGraphRunner
from backend.config import RETRY_BACKOFF_MS, STREAM_STEP_DELAY_MS
from backend.errors import AppError, RetryableToolError
from backend.models import TraceStep, TurnExecution
from backend.safety.guard import SafetyGuard
from backend.tools.calculator import CalculatorTool
from backend.tools.currency_converter import CurrencyConverterTool
from backend.tools.text_processor import TextProcessorTool
from backend.tools.transaction_categorizer import TransactionCategorizerTool
from backend.tools.weather_mock import WeatherMockTool


INPUT_VALIDATION_ERRORS = {"EMPTY_INPUT", "INPUT_TOO_LONG", "TASK_TOO_COMPLEX"}
TOOL_LABELS = {
    "TextProcessorTool": "Text",
    "CalculatorTool": "Calculator",
    "WeatherMockTool": "Weather",
    "CurrencyConverterTool": "Currency",
    "TransactionCategorizerTool": "Categorization",
}


class AgentController:
    def __init__(self):
        self.guard = SafetyGuard()
        self.interpreter = TaskInterpreter()
        self.stream_step_delay_ms = STREAM_STEP_DELAY_MS
        self.tools = {
            "TextProcessorTool": TextProcessorTool(),
            "CalculatorTool": CalculatorTool(),
            "WeatherMockTool": WeatherMockTool(),
            "CurrencyConverterTool": CurrencyConverterTool(),
            "TransactionCategorizerTool": TransactionCategorizerTool(),
        }

    def execute_task(self, task_text: str, trace_id: str) -> TurnExecution:
        stream = self.execute_task_stream(task_text, trace_id, pacing_enabled=False)
        try:
            while True:
                next(stream)
        except StopIteration as stopped:
            return stopped.value

    def execute_task_stream(
        self,
        task_text: str,
        trace_id: str,
        *,
        pacing_enabled: bool,
    ) -> Generator[dict[str, Any], None, TurnExecution]:
        turn_id = str(uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        yield self._stream_event(
            "run_started",
            {
                "turn_id": turn_id,
                "task_text": task_text,
                "timestamp": timestamp,
                "trace_id": trace_id,
            },
        )
        runner = TaskExecutionGraphRunner(self, pacing_enabled=pacing_enabled)
        initial_state = {
            "collected_results": [],
            "context": {},
            "executed_tools": [],
            "steps": [],
            "task_text": task_text,
            "timestamp": timestamp,
            "trace_id": trace_id,
            "turn_id": turn_id,
        }
        return (yield from runner.execute(initial_state))

    def _append_trace_step(
        self,
        steps: list[TraceStep],
        *,
        phase: str,
        status: str,
        message: str,
        tool_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> tuple[TraceStep, list[TraceStep]]:
        next_steps = [
            *steps,
            TraceStep(
                step_number=len(steps) + 1,
                phase=phase,
                status=status,
                message=message,
                tool_name=tool_name,
                payload=payload,
            ),
        ]
        return next_steps[-1], next_steps

    def _build_issue_turn(
        self,
        *,
        turn_id: str,
        task_text: str,
        sanitized_text: str,
        trace_id: str,
        timestamp: str,
        steps: list[TraceStep],
        tools_used: list[str],
        issue: AppError,
        collected_results: list[dict[str, Any]],
    ) -> TurnExecution:
        issue_summary = self._issue_summary(issue)
        if collected_results:
            final_output = "\n".join(
                [f"{index}. {result['summary']}" for index, result in enumerate(collected_results, start=1)]
                + [f"{len(collected_results) + 1}. {issue_summary}"]
            )
            status = "partial"
        elif issue.error_code == "UNSUPPORTED_TASK":
            final_output = issue_summary
            status = "unsupported"
        else:
            final_output = issue_summary
            status = "failed"

        output_data: dict[str, Any] = {
            "issue": self._issue_payload(issue),
            "supported_tasks": self._supported_task_examples(),
        }
        if collected_results:
            output_data["results"] = collected_results

        response_step = TraceStep(
            step_number=len(steps) + 1,
            phase="response_assembly",
            status="completed",
            message="Returned a handled response with trace context and suggestions.",
        )
        final_steps = [*steps, response_step]

        return TurnExecution(
            turn_id=turn_id,
            task_text=task_text,
            sanitized_text=sanitized_text,
            status=status,
            final_output=final_output,
            output_data=output_data,
            tools_used=tools_used,
            execution_steps=final_steps,
            timestamp=timestamp,
            trace_id=trace_id,
        )

    def _stream_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"type": event_type, **payload}

    def _trace_event(self, step: TraceStep, *, trace_id: str) -> dict[str, Any]:
        return self._stream_event(
            "trace_step",
            {
                "step": asdict(step),
                "trace_id": trace_id,
            },
        )

    def _retry_event(self, step: TraceStep, *, trace_id: str) -> dict[str, Any]:
        return self._stream_event(
            "retry_scheduled",
            {
                "step": asdict(step),
                "trace_id": trace_id,
                "delay_ms": int((step.payload or {}).get("delay_ms", 0)),
            },
        )

    def _maybe_pause(self, pacing_enabled: bool, delay_ms: int = STREAM_STEP_DELAY_MS) -> None:
        if pacing_enabled and delay_ms > 0:
            sleep(delay_ms / 1000)

    def _retry_delay_ms(self, pacing_enabled: bool) -> int:
        return RETRY_BACKOFF_MS if pacing_enabled else 0

    def _is_handled_execution_error(self, error: AppError) -> bool:
        return isinstance(error, RetryableToolError) or (
            error.status_code == 422 and error.error_code not in INPUT_VALIDATION_ERRORS
        )

    def _planning_message(self, tools_used: list[str]) -> str:
        labels = [self._tool_label(tool_name) for tool_name in tools_used]
        if not labels:
            return "No tool plan was created."
        if len(labels) == 1:
            return f"Planned a single tool step: {labels[0]}."
        return f"Planned {len(labels)} tool steps: {' -> '.join(labels)}."

    def _issue_summary(self, error: AppError) -> str:
        if error.error_code == "UNSUPPORTED_TASK":
            return "TaskBuddy could not match this request to a supported tool."
        if isinstance(error, RetryableToolError):
            return f"TaskBuddy hit a temporary tool failure. {error.message}"
        return f"TaskBuddy could not complete this request. {error.message}"

    def _issue_payload(self, error: AppError) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error_code": error.error_code,
            "message": error.message,
            "suggestions": self._issue_suggestions(error),
        }
        if error.details:
            payload["details"] = error.details
        return payload

    def _issue_suggestions(self, error: AppError) -> list[str]:
        if isinstance(error, RetryableToolError):
            return ["Retry the request. TaskBuddy records retry attempts in the execution trace."]
        if error.error_code == "CITY_NOT_SUPPORTED":
            supported_cities = error.details.get("supported_cities", [])
            return [f"Try one of the supported cities: {', '.join(supported_cities)}."] if supported_cities else []
        if error.error_code in {"INVALID_EXPRESSION", "DIVIDE_BY_ZERO"}:
            return ['Try a basic arithmetic request such as "calculate 25 * 3".']
        if error.error_code in {"INVALID_AMOUNT", "CURRENCY_NOT_SUPPORTED"}:
            return ['Use a supported currency pair such as "Convert 45 CAD to USD".']
        if error.error_code in {"TRANSACTION_DESCRIPTION_REQUIRED"}:
            return ['Include a merchant or transaction description, for example "Categorize Starbucks transaction 45 CAD".']
        if error.error_code in {"TEXT_TARGET_REQUIRED", "TEXT_OPERATION_UNSUPPORTED"}:
            return ['Provide a text target, for example "Convert \\"task buddy\\" to uppercase".']
        if error.error_code == "UNSUPPORTED_TASK":
            return self._supported_task_examples()
        return []

    def _supported_task_examples(self) -> list[str]:
        return [
            'Convert "task buddy" to uppercase',
            "What is the weather in Toronto?",
            "Categorize Starbucks transaction 45 CAD and convert to USD",
        ]

    def _tool_label(self, tool_name: str) -> str:
        return TOOL_LABELS.get(tool_name, tool_name.replace("Tool", ""))
