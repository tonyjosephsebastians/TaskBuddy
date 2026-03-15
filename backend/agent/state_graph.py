from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.errors import AppError, RetryableToolError
from backend.models import ParsedTask, ToolStep, TraceStep, TurnExecution


if TYPE_CHECKING:
    from backend.agent.controller import AgentController


class TaskGraphState(TypedDict, total=False):
    collected_results: list[dict[str, Any]]
    context: dict[str, str]
    current_index: int
    executed_tools: list[str]
    final_output: str
    issue: AppError
    output_data: dict[str, Any]
    parsed: ParsedTask
    planned_tools: list[str]
    retry_count: int
    sanitized_text: str
    steps: list[TraceStep]
    task_text: str
    timestamp: str
    trace_id: str
    turn_execution: TurnExecution
    turn_id: str


class TaskExecutionGraphRunner:
    def __init__(self, controller: AgentController, *, pacing_enabled: bool):
        self.controller = controller
        self.pacing_enabled = pacing_enabled
        self._pending_events: list[tuple[dict[str, Any], int | None]] = []
        self._graph = self._build_graph().compile()

    def execute(self, state: TaskGraphState):
        final_state: TaskGraphState = state
        for next_state in self._graph.stream(state, stream_mode="values"):
            final_state = next_state
            yield from self._drain_events()

        yield from self._drain_events()
        return final_state["turn_execution"]

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(TaskGraphState)
        graph.add_node("validation", self._validate_input)
        graph.add_node("planning", self._plan_execution)
        graph.add_node("execute_tool", self._execute_tool)
        graph.add_node("issue_response", self._assemble_issue_response)
        graph.add_node("response_assembly", self._assemble_response)

        graph.add_edge(START, "validation")
        graph.add_edge("validation", "planning")
        graph.add_conditional_edges(
            "planning",
            self._after_planning,
            {
                "execute_tool": "execute_tool",
                "issue_response": "issue_response",
            },
        )
        graph.add_conditional_edges(
            "execute_tool",
            self._after_tool_execution,
            {
                "execute_tool": "execute_tool",
                "issue_response": "issue_response",
                "response_assembly": "response_assembly",
            },
        )
        graph.add_edge("issue_response", END)
        graph.add_edge("response_assembly", END)
        return graph

    def _validate_input(self, state: TaskGraphState) -> TaskGraphState:
        sanitized_text = self.controller.guard.validate(state["task_text"])
        step, steps = self.controller._append_trace_step(
            state.get("steps", []),
            phase="validation",
            status="completed",
            message="Checked request length and normalized the input.",
        )
        self._queue_event(self.controller._trace_event(step, trace_id=state["trace_id"]))
        return {
            "sanitized_text": sanitized_text,
            "steps": steps,
        }

    def _plan_execution(self, state: TaskGraphState) -> TaskGraphState:
        try:
            parsed = self.controller.interpreter.interpret(state["task_text"], state["sanitized_text"])
        except AppError as error:
            if not self.controller._is_handled_execution_error(error):
                raise
            step, steps = self.controller._append_trace_step(
                state.get("steps", []),
                phase="planning",
                status="failed",
                message=self.controller._issue_summary(error),
                payload=self.controller._issue_payload(error),
            )
            self._queue_event(self.controller._trace_event(step, trace_id=state["trace_id"]))
            return {
                "issue": error,
                "steps": steps,
            }

        planned_tools = [step.tool_name for step in parsed.steps]
        step, steps = self.controller._append_trace_step(
            state.get("steps", []),
            phase="planning",
            status="completed",
            message=self.controller._planning_message(planned_tools),
            payload={"tools_used": [self.controller._tool_label(tool_name) for tool_name in planned_tools]},
        )
        self._queue_event(self.controller._trace_event(step, trace_id=state["trace_id"]))
        return {
            "current_index": 0,
            "parsed": parsed,
            "planned_tools": planned_tools,
            "retry_count": 0,
            "steps": steps,
        }

    def _execute_tool(self, state: TaskGraphState) -> TaskGraphState:
        parsed = state["parsed"]
        current_index = state.get("current_index", 0)
        tool_step: ToolStep = parsed.steps[current_index]
        tool = self.controller.tools[tool_step.tool_name]
        params = dict(tool_step.params)
        if params.pop("text_from_context_key", None):
            params["text"] = state.get("context", {}).get("previous_summary", "")

        retry_count = state.get("retry_count", 0)
        try:
            result = tool.execute(params, state.get("context", {}))
        except RetryableToolError as error:
            if retry_count >= 1:
                step, steps = self.controller._append_trace_step(
                    state.get("steps", []),
                    phase="tool_execution",
                    status="failed",
                    message=self.controller._issue_summary(error),
                    tool_name=tool.name,
                    payload=self.controller._issue_payload(error),
                )
                self._queue_event(self.controller._trace_event(step, trace_id=state["trace_id"]))
                return {
                    "issue": error,
                    "steps": steps,
                }

            next_retry_count = retry_count + 1
            retry_delay_ms = self.controller._retry_delay_ms(self.pacing_enabled)
            step, steps = self.controller._append_trace_step(
                state.get("steps", []),
                phase="tool_execution",
                status="retrying",
                message=f"Temporary issue while running {self.controller._tool_label(tool.name)}. Retrying once.",
                tool_name=tool.name,
                payload={
                    "retry_count": next_retry_count,
                    "delay_ms": retry_delay_ms,
                    "error_code": error.error_code,
                    "message": error.message,
                },
            )
            self._queue_event(
                self.controller._retry_event(step, trace_id=state["trace_id"]),
                delay_ms=retry_delay_ms,
            )
            return {
                "retry_count": next_retry_count,
                "steps": steps,
            }
        except AppError as error:
            if not self.controller._is_handled_execution_error(error):
                raise
            step, steps = self.controller._append_trace_step(
                state.get("steps", []),
                phase="tool_execution",
                status="failed",
                message=self.controller._issue_summary(error),
                tool_name=tool.name,
                payload=self.controller._issue_payload(error),
            )
            self._queue_event(self.controller._trace_event(step, trace_id=state["trace_id"]))
            return {
                "issue": error,
                "steps": steps,
            }

        executed_tools = [*state.get("executed_tools", []), tool.name]
        collected_results = [
            *state.get("collected_results", []),
            {"tool_name": tool.name, "summary": result.summary, "data": result.data},
        ]
        context = {**state.get("context", {}), "previous_summary": result.summary}
        step, steps = self.controller._append_trace_step(
            state.get("steps", []),
            phase="tool_execution",
            status=result.status,
            message=result.trace_message,
            tool_name=tool.name,
            payload=result.data,
        )
        self._queue_event(self.controller._trace_event(step, trace_id=state["trace_id"]))
        return {
            "collected_results": collected_results,
            "context": context,
            "current_index": current_index + 1,
            "executed_tools": executed_tools,
            "final_output": result.summary,
            "output_data": result.data,
            "retry_count": 0,
            "steps": steps,
        }

    def _assemble_issue_response(self, state: TaskGraphState) -> TaskGraphState:
        turn = self.controller._build_issue_turn(
            turn_id=state["turn_id"],
            task_text=state["task_text"],
            sanitized_text=state["sanitized_text"],
            trace_id=state["trace_id"],
            timestamp=state["timestamp"],
            steps=state.get("steps", []),
            tools_used=state.get("executed_tools", []),
            issue=state["issue"],
            collected_results=state.get("collected_results", []),
        )
        self._queue_event(self.controller._trace_event(turn.execution_steps[-1], trace_id=state["trace_id"]))
        return {
            "steps": turn.execution_steps,
            "turn_execution": turn,
        }

    def _assemble_response(self, state: TaskGraphState) -> TaskGraphState:
        parsed = state["parsed"]
        collected_results = state.get("collected_results", [])
        final_output = state.get("final_output", "")
        output_data = state.get("output_data", {})

        if parsed.metadata.get("combine_results"):
            final_output = "\n".join(
                f"{index}. {result['summary']}" for index, result in enumerate(collected_results, start=1)
            )
            output_data = {"results": collected_results}

        step, steps = self.controller._append_trace_step(
            state.get("steps", []),
            phase="response_assembly",
            status="completed",
            message="Assembled final output, trace details, and structured data.",
        )
        self._queue_event(self.controller._trace_event(step, trace_id=state["trace_id"]))
        turn = TurnExecution(
            turn_id=state["turn_id"],
            task_text=state["task_text"],
            sanitized_text=state["sanitized_text"],
            status="completed",
            final_output=final_output,
            output_data=output_data,
            tools_used=state["planned_tools"],
            execution_steps=steps,
            timestamp=state["timestamp"],
            trace_id=state["trace_id"],
        )
        return {
            "final_output": final_output,
            "output_data": output_data,
            "steps": steps,
            "turn_execution": turn,
        }

    def _after_planning(self, state: TaskGraphState) -> str:
        if state.get("issue") is not None:
            return "issue_response"
        return "execute_tool"

    def _after_tool_execution(self, state: TaskGraphState) -> str:
        if state.get("issue") is not None:
            return "issue_response"
        if state.get("current_index", 0) < len(state["parsed"].steps):
            return "execute_tool"
        return "response_assembly"

    def _queue_event(self, event: dict[str, Any], *, delay_ms: int | None = None) -> None:
        self._pending_events.append((event, delay_ms))

    def _drain_events(self):
        while self._pending_events:
            event, delay_ms = self._pending_events.pop(0)
            yield event
            pause_delay = self.controller.stream_step_delay_ms if delay_ms is None else delay_ms
            self.controller._maybe_pause(self.pacing_enabled, pause_delay)
