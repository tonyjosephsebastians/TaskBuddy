from pathlib import Path

from backend.agent.controller import AgentController
from backend.agent.interpreter import TaskInterpreter
from backend.config import DEFAULT_ADMIN_PASSWORD
from backend.errors import AppError, RetryableToolError
from backend.models import ToolResult
from backend.persistence.repository import TaskRepository
from backend.security import verify_password


def test_interpreter_routes_all_primary_tools():
    interpreter = TaskInterpreter()
    assert interpreter.interpret('Convert "hello" to uppercase', 'Convert "hello" to uppercase').steps[0].tool_name == "TextProcessorTool"
    assert interpreter.interpret("What is (3 + 4) * 2?", "What is (3 + 4) * 2?").steps[0].tool_name == "CalculatorTool"
    assert interpreter.interpret("Add 3+2", "Add 3+2").steps[0].tool_name == "CalculatorTool"
    assert interpreter.interpret("What is the weather in Toronto?", "What is the weather in Toronto?").steps[0].tool_name == "WeatherMockTool"
    assert interpreter.interpret("Convert 100 CAD to USD", "Convert 100 CAD to USD").steps[0].tool_name == "CurrencyConverterTool"
    assert interpreter.interpret("Categorize Starbucks transaction", "Categorize Starbucks transaction").steps[0].tool_name == "TransactionCategorizerTool"


def test_interpreter_routes_supported_synonym_prompts():
    interpreter = TaskInterpreter()

    word_count_step = interpreter.interpret('Count the word "test"', 'Count the word "test"').steps[0]
    assert word_count_step.tool_name == "TextProcessorTool"
    assert word_count_step.params == {"operation": "word_count", "text": "test"}

    calculator_step = interpreter.interpret("What is 8 minus 3?", "What is 8 minus 3?").steps[0]
    assert calculator_step.tool_name == "CalculatorTool"
    assert calculator_step.params == {"expression": "8 - 3"}

    weather_step = interpreter.interpret("Forecast for London", "Forecast for London").steps[0]
    assert weather_step.tool_name == "WeatherMockTool"
    assert weather_step.params == {"city": "london"}

    currency_step = interpreter.interpret("Exchange 15 USD to CAD", "Exchange 15 USD to CAD").steps[0]
    assert currency_step.tool_name == "CurrencyConverterTool"
    assert currency_step.params == {"amount": "15", "from_currency": "USD", "to_currency": "CAD"}

    transaction_step = interpreter.interpret("Classify Starbucks spend", "Classify Starbucks spend").steps[0]
    assert transaction_step.tool_name == "TransactionCategorizerTool"
    assert transaction_step.params == {"description": "Starbucks", "amount": None}


def test_interpreter_routes_explicit_unsupported_currency_target_to_converter():
    interpreter = TaskInterpreter()
    step = interpreter.interpret("Convert 67 CAD to INR", "Convert 67 CAD to INR").steps[0]

    assert step.tool_name == "CurrencyConverterTool"
    assert step.params == {"amount": "67", "from_currency": "CAD", "to_currency": "INR"}


def test_interpreter_keeps_same_currency_fallback_when_target_is_not_provided():
    interpreter = TaskInterpreter()
    step = interpreter.interpret("Convert 67 CAD", "Convert 67 CAD").steps[0]

    assert step.tool_name == "CurrencyConverterTool"
    assert step.params == {"amount": "67", "from_currency": "CAD", "to_currency": "CAD"}


def test_interpreter_routes_transaction_prompt_with_currency_amount_to_categorizer():
    interpreter = TaskInterpreter()
    parsed = interpreter.interpret(
        "Categorize Starbucks transaction 45 CAD",
        "Categorize Starbucks transaction 45 CAD",
    )

    assert [step.tool_name for step in parsed.steps] == ["TransactionCategorizerTool"]
    assert parsed.steps[0].params == {"description": "Starbucks 45 CAD", "amount": 45.0}


def test_interpreter_builds_two_step_transaction_and_currency_plan():
    interpreter = TaskInterpreter()
    parsed = interpreter.interpret(
        "Categorize Starbucks transaction 45 CAD and convert to USD",
        "Categorize Starbucks transaction 45 CAD and convert to USD",
    )
    assert [step.tool_name for step in parsed.steps] == ["TransactionCategorizerTool", "CurrencyConverterTool"]
    assert parsed.metadata["combine_results"] is True


def test_interpreter_builds_two_independent_subtasks_from_natural_language():
    interpreter = TaskInterpreter()
    parsed = interpreter.interpret(
        "What is the weather in Toronto and calculate 25 * 3",
        "What is the weather in Toronto and calculate 25 * 3",
    )

    assert [step.tool_name for step in parsed.steps] == ["WeatherMockTool", "CalculatorTool"]
    assert parsed.metadata["combine_results"] is True


def test_interpreter_supports_unquoted_text_task_in_multi_subtask_mode():
    interpreter = TaskInterpreter()
    parsed = interpreter.interpret(
        "Convert hello to uppercase and weather in London",
        "Convert hello to uppercase and weather in London",
    )

    assert parsed.steps[0].tool_name == "TextProcessorTool"
    assert parsed.steps[0].params["text"] == "hello"
    assert parsed.steps[1].tool_name == "WeatherMockTool"


def test_interpreter_keeps_quoted_and_inside_single_text_task():
    interpreter = TaskInterpreter()
    parsed = interpreter.interpret(
        'Convert "task buddy and test bussy and file buddy" to uppercase',
        'Convert "task buddy and test bussy and file buddy" to uppercase',
    )

    assert [step.tool_name for step in parsed.steps] == ["TextProcessorTool"]
    assert parsed.steps[0].params == {
        "operation": "uppercase",
        "text": "task buddy and test bussy and file buddy",
    }


def test_interpreter_supports_single_quoted_text_without_false_subtask_split():
    interpreter = TaskInterpreter()
    parsed = interpreter.interpret(
        "Convert 'task buddy and test bussy' to uppercase",
        "Convert 'task buddy and test bussy' to uppercase",
    )

    assert [step.tool_name for step in parsed.steps] == ["TextProcessorTool"]
    assert parsed.steps[0].params == {
        "operation": "uppercase",
        "text": "task buddy and test bussy",
    }


def test_interpreter_keeps_apostrophes_inside_words_outside_quote_mode():
    interpreter = TaskInterpreter()
    parsed = interpreter.interpret(
        "Convert don't panic to uppercase and weather in Toronto",
        "Convert don't panic to uppercase and weather in Toronto",
    )

    assert [step.tool_name for step in parsed.steps] == ["TextProcessorTool", "WeatherMockTool"]
    assert parsed.steps[0].params == {"operation": "uppercase", "text": "don't panic"}


def test_interpreter_rejects_three_real_subtasks_even_with_quoted_and():
    interpreter = TaskInterpreter()

    try:
        interpreter.interpret(
            'Convert "a and b" to uppercase and weather in Toronto and calculate 2+2',
            'Convert "a and b" to uppercase and weather in Toronto and calculate 2+2',
        )
    except AppError as error:
        assert error.error_code == "TASK_TOO_COMPLEX"
        assert error.message == "Multi-tool execution supports up to 2 subtasks per request."
    else:
        raise AssertionError("Expected AppError")


def test_interpreter_rejects_more_than_two_subtasks():
    interpreter = TaskInterpreter()
    try:
        interpreter.interpret(
            "Convert hello to uppercase and calculate 25 * 3 and weather in Toronto",
            "Convert hello to uppercase and calculate 25 * 3 and weather in Toronto",
        )
    except AppError as error:
        assert error.error_code == "TASK_TOO_COMPLEX"
        assert error.message == "Multi-tool execution supports up to 2 subtasks per request."
    else:
        raise AssertionError("Expected AppError")


def test_controller_combines_multi_subtask_results():
    controller = AgentController()
    execution = controller.execute_task("What is the weather in Toronto and calculate 25 * 3", trace_id="trace-456")

    assert execution.tools_used == ["WeatherMockTool", "CalculatorTool"]
    assert execution.final_output == "1. Toronto: Cloudy, 8C, humidity 71%.\n2. 75.0"
    assert len(execution.output_data["results"]) == 2


def test_controller_counts_words_for_count_the_word_prompt():
    controller = AgentController()
    execution = controller.execute_task('Count the word "test"', trace_id="trace-word-count")

    assert execution.status == "completed"
    assert execution.tools_used == ["TextProcessorTool"]
    assert execution.final_output == "1"
    assert execution.output_data == {"operation": "word_count", "input": "test", "result": 1}


def test_controller_combines_transaction_and_currency_results():
    controller = AgentController()
    execution = controller.execute_task(
        "Categorize Starbucks transaction 45 CAD and convert to USD",
        trace_id="trace-finance",
    )

    assert execution.status == "completed"
    assert execution.tools_used == ["TransactionCategorizerTool", "CurrencyConverterTool"]
    assert execution.final_output == "1. Category: dining\n2. 45.00 CAD = 33.33 USD"
    assert len(execution.output_data["results"]) == 2
    assert execution.output_data["results"][0]["tool_name"] == "TransactionCategorizerTool"
    assert execution.output_data["results"][1]["tool_name"] == "CurrencyConverterTool"


def test_controller_returns_handled_failure_for_explicit_unsupported_currency_target():
    controller = AgentController()
    execution = controller.execute_task("Convert 67 CAD to INR", trace_id="trace-currency-unsupported")

    assert execution.status == "failed"
    assert execution.tools_used == []
    assert execution.final_output == "TaskBuddy could not complete this request. Only USD, CAD, GBP, and AUD are supported."
    assert execution.output_data["issue"]["error_code"] == "CURRENCY_NOT_SUPPORTED"
    assert execution.output_data["issue"]["details"]["supported_currencies"] == ["USD", "CAD", "GBP", "AUD"]


def test_controller_returns_handled_unsupported_turn():
    controller = AgentController()
    execution = controller.execute_task("Summarize the latest stock market news", trace_id="trace-789")

    assert execution.status == "unsupported"
    assert execution.final_output == "TaskBuddy could not match this request to a supported tool."
    assert execution.tools_used == []
    assert execution.execution_steps[-1].phase == "response_assembly"


def test_controller_returns_handled_unsupported_turn_for_occurrence_count_prompt():
    controller = AgentController()
    execution = controller.execute_task('Count occurrences of "test" in "test test"', trace_id="trace-occurrence")

    assert execution.status == "unsupported"
    assert execution.final_output == "TaskBuddy could not match this request to a supported tool."
    assert execution.tools_used == []


def test_controller_retries_retryable_tool_failures_once():
    controller = AgentController()

    class FlakyTextTool:
        name = "TextProcessorTool"

        def __init__(self):
            self.calls = 0

        def execute(self, params, context):
            self.calls += 1
            if self.calls == 1:
                raise RetryableToolError("TEXT_TOOL_TEMPORARY_FAILURE", "The text tool timed out briefly.")
            return ToolResult(
                summary="HELLO",
                data={"operation": "uppercase", "result": "HELLO"},
                trace_message="Applied uppercase to the text input.",
            )

    flaky_tool = FlakyTextTool()
    controller.tools["TextProcessorTool"] = flaky_tool

    execution = controller.execute_task('Convert "hello" to uppercase', trace_id="trace-retry")

    retry_steps = [step for step in execution.execution_steps if step.status == "retrying"]
    assert execution.status == "completed"
    assert execution.final_output == "HELLO"
    assert flaky_tool.calls == 2
    assert len(retry_steps) == 1
    assert retry_steps[0].payload == {
        "retry_count": 1,
        "delay_ms": 0,
        "error_code": "TEXT_TOOL_TEMPORARY_FAILURE",
        "message": "The text tool timed out briefly.",
    }


def test_controller_returns_failed_turn_when_retryable_error_keeps_failing():
    controller = AgentController()

    class AlwaysFailingTextTool:
        name = "TextProcessorTool"

        def execute(self, params, context):
            raise RetryableToolError("TEXT_TOOL_TEMPORARY_FAILURE", "The text tool timed out briefly.")

    controller.tools["TextProcessorTool"] = AlwaysFailingTextTool()

    execution = controller.execute_task('Convert "hello" to uppercase', trace_id="trace-retry-fail")

    assert execution.status == "failed"
    assert "temporary tool failure" in execution.final_output.lower()
    assert execution.execution_steps[-1].phase == "response_assembly"


def test_repository_seeds_default_users(tmp_path: Path):
    repository = TaskRepository(tmp_path / "test.db")
    repository.initialize()
    admin = repository.get_user_by_username("admin")
    analyst1 = repository.get_user_by_username("analyst1")
    analyst2 = repository.get_user_by_username("analyst2")

    assert admin is not None
    assert admin.role == "admin"
    assert admin.password_hash is not None
    assert admin.password_salt is not None
    assert verify_password(DEFAULT_ADMIN_PASSWORD, admin.password_hash, admin.password_salt)
    assert analyst1 is None
    assert analyst2 is None


def test_thread_persists_masked_turns_and_auto_titles(tmp_path: Path):
    repository = TaskRepository(tmp_path / "test.db")
    repository.initialize()
    admin = repository.get_user_by_username("admin")
    assert admin is not None

    controller = AgentController()
    thread = repository.create_thread(admin.user_id)
    execution = controller.execute_task("Convert 1234567890123456 USD to CAD", trace_id="trace-123")
    repository.save_turn(thread.thread_id, admin.user_id, execution)

    saved_thread = repository.get_thread(thread.thread_id, admin.user_id)
    assert saved_thread is not None
    assert saved_thread.title.startswith("Convert")
    assert "******" in saved_thread.turns[0].task_text
    assert saved_thread.turns[0].trace_id == "trace-123"


def test_repository_enforces_password_policy_for_created_users(tmp_path: Path):
    repository = TaskRepository(tmp_path / "test.db")
    repository.initialize()

    try:
        repository.create_user("reviewer", "password1", "user")
    except AppError as error:
        assert error.error_code == "INVALID_PASSWORD"
        assert error.message == "Password must include at least 1 uppercase letter."
    else:
        raise AssertionError("Expected AppError")


def test_repository_enforces_role_limits_for_created_users(tmp_path: Path):
    repository = TaskRepository(tmp_path / "test.db")
    repository.initialize()
    repository.create_user("reviewer", "Reviewer1", "user")
    repository.create_user("analyst", "Analyst1", "user")

    try:
        repository.create_user("auditor", "Auditor1", "user")
    except AppError as error:
        assert error.error_code == "ROLE_LIMIT_REACHED"
        assert error.message == "TaskBuddy supports up to 2 standard user accounts."
    else:
        raise AssertionError("Expected AppError")


def test_repository_enforces_thread_limit(tmp_path: Path):
    repository = TaskRepository(tmp_path / "test.db")
    repository.initialize()
    admin = repository.get_user_by_username("admin")
    assert admin is not None

    for _ in range(5):
        repository.create_thread(admin.user_id)

    try:
        repository.create_thread(admin.user_id)
    except AppError as error:
        assert error.error_code == "THREAD_LIMIT_REACHED"
    else:
        raise AssertionError("Expected AppError")


def test_repository_enforces_thread_flow_limit(tmp_path: Path):
    repository = TaskRepository(tmp_path / "test.db")
    repository.initialize()
    admin = repository.get_user_by_username("admin")
    assert admin is not None

    controller = AgentController()
    thread = repository.create_thread(admin.user_id)
    for index in range(3):
        execution = controller.execute_task(f"Calculate {index + 1} + 1", trace_id=f"trace-{index}")
        repository.save_turn(thread.thread_id, admin.user_id, execution)

    try:
        repository.ensure_thread_flow_capacity(thread.thread_id, admin.user_id)
    except AppError as error:
        assert error.error_code == "THREAD_FLOW_LIMIT_REACHED"
    else:
        raise AssertionError("Expected AppError")
