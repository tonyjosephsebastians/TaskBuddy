import json
from pathlib import Path

from fastapi.testclient import TestClient

import backend.api.routes as api_routes
from backend.app import create_app
from backend.errors import RetryableToolError
from backend.models import ToolResult
from backend.persistence.repository import TaskRepository


def create_test_app(tmp_path: Path):
    repository = TaskRepository(tmp_path / "api-test.db")
    repository.initialize()
    api_routes.DEMO_PACING_ENABLED = False
    return create_app(repository=repository)


def create_test_client(tmp_path: Path) -> TestClient:
    return TestClient(create_test_app(tmp_path))


def collect_sse_events(response: TestClient) -> list[dict[str, object]]:
    payload = "".join(response.iter_text())
    events: list[dict[str, object]] = []
    for block in payload.split("\n\n"):
        raw_block = block.strip()
        if not raw_block:
            continue
        event_name = "message"
        data = ""
        for line in raw_block.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
        if data:
            events.append({"event": event_name, "data": json.loads(data)})
    return events


def login_as_admin(client: TestClient):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    return response


def test_health_endpoint(tmp_path: Path):
    client = create_test_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_flow_and_me_endpoint(tmp_path: Path):
    client = create_test_client(tmp_path)

    unauthorized = client.get("/api/v1/auth/me")
    assert unauthorized.status_code == 401

    login_response = login_as_admin(client)
    assert login_response.json()["role"] == "admin"
    assert "taskbuddy_session" in login_response.cookies

    me_response = client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "admin"


def test_admin_can_create_user_and_user_cannot_access_admin_route(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    existing_users = client.get("/api/v1/admin/users")
    assert existing_users.status_code == 200

    create_user_response = client.post(
        "/api/v1/admin/users",
        json={"username": "tony", "password": "Password1", "role": "user"},
    )
    assert create_user_response.status_code == 200

    list_users_response = client.get("/api/v1/admin/users")
    assert list_users_response.status_code == 200
    assert any(user["username"] == "tony" for user in list_users_response.json())

    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"username": "tony", "password": "Password1"})
    forbidden_response = client.get("/api/v1/admin/users")
    assert forbidden_response.status_code == 403


def test_threads_append_turns_and_support_search(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    create_thread_response = client.post("/api/v1/threads")
    assert create_thread_response.status_code == 200
    thread = create_thread_response.json()

    first_turn_response = client.post(
        f"/api/v1/threads/{thread['thread_id']}/tasks",
        json={"task_text": 'Convert "hello" to uppercase'},
    )
    assert first_turn_response.status_code == 200
    assert first_turn_response.json()["final_output"] == "HELLO"

    second_turn_response = client.post(
        f"/api/v1/threads/{thread['thread_id']}/tasks",
        json={"task_text": "What is the weather in Toronto?"},
    )
    assert second_turn_response.status_code == 200

    detail_response = client.get(f"/api/v1/threads/{thread['thread_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["title"].startswith('Convert "hello"')
    assert len(detail["turns"]) == 2
    assert detail["turns"][1]["tools_used"] == ["WeatherMockTool"]

    search_response = client.get("/api/v1/threads?search=Toronto")
    assert search_response.status_code == 200
    assert search_response.json()[0]["thread_id"] == thread["thread_id"]


def test_api_rejects_sixth_thread(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    for _ in range(5):
        response = client.post("/api/v1/threads")
        assert response.status_code == 200

    response = client.post("/api/v1/threads")
    assert response.status_code == 422
    assert response.json()["error_code"] == "THREAD_LIMIT_REACHED"


def test_api_rejects_fourth_thread_flow_before_execution(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    thread = client.post("/api/v1/threads").json()
    for _ in range(3):
        response = client.post(
            f"/api/v1/threads/{thread['thread_id']}/tasks",
            json={"task_text": 'Convert "hello" to uppercase'},
        )
        assert response.status_code == 200

    response = client.post(
        f"/api/v1/threads/{thread['thread_id']}/tasks",
        json={"task_text": 'Convert "blocked" to uppercase'},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "THREAD_FLOW_LIMIT_REACHED"


def test_api_rejects_fourth_thread_flow_on_stream_route(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    thread = client.post("/api/v1/threads").json()
    for _ in range(3):
        response = client.post(
            f"/api/v1/threads/{thread['thread_id']}/tasks",
            json={"task_text": 'Convert "hello" to uppercase'},
        )
        assert response.status_code == 200

    response = client.post(
        f"/api/v1/threads/{thread['thread_id']}/tasks/stream",
        json={"task_text": 'Convert "blocked" to uppercase'},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "THREAD_FLOW_LIMIT_REACHED"


def test_thread_can_be_deleted(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    thread = client.post("/api/v1/threads").json()
    client.post(
        f"/api/v1/threads/{thread['thread_id']}/tasks",
        json={"task_text": 'Convert "hello" to uppercase'},
    )

    delete_response = client.delete(f"/api/v1/threads/{thread['thread_id']}")
    assert delete_response.status_code == 204

    missing_response = client.get(f"/api/v1/threads/{thread['thread_id']}")
    assert missing_response.status_code == 404

    list_response = client.get("/api/v1/threads")
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_api_supports_two_subtasks_in_one_request(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    thread = client.post("/api/v1/threads").json()
    response = client.post(
        f"/api/v1/threads/{thread['thread_id']}/tasks",
        json={"task_text": "What is the weather in Toronto and calculate 25 * 3"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tools_used"] == ["WeatherMockTool", "CalculatorTool"]
    assert "1. Toronto: Cloudy, 8C, humidity 71%." in body["final_output"]
    assert "2. 75.0" in body["final_output"]
    assert len(body["output_data"]["results"]) == 2


def test_api_rejects_more_than_two_subtasks(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    thread = client.post("/api/v1/threads").json()
    response = client.post(
        f"/api/v1/threads/{thread['thread_id']}/tasks",
        json={"task_text": "Convert hello to uppercase and calculate 25 * 3 and weather in Toronto"},
    )

    assert response.status_code == 422
    assert response.json()["message"] == "Multi-tool execution supports up to 2 subtasks per request."


def test_api_returns_handled_response_for_unsupported_tasks(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    thread = client.post("/api/v1/threads").json()
    response = client.post(
        f"/api/v1/threads/{thread['thread_id']}/tasks",
        json={"task_text": "Summarize the latest stock market news"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unsupported"
    assert body["final_output"] == "TaskBuddy could not match this request to a supported tool."
    assert body["tools_used"] == []


def test_api_streams_trace_steps_and_returns_completed_thread(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    thread = client.post("/api/v1/threads").json()
    with client.stream(
        "POST",
        f"/api/v1/threads/{thread['thread_id']}/tasks/stream",
        json={"task_text": 'Convert "hello" to uppercase'},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = collect_sse_events(response)

    assert [event["event"] for event in events] == [
        "run_started",
        "trace_step",
        "trace_step",
        "trace_step",
        "trace_step",
        "completed",
    ]
    completed = events[-1]["data"]
    assert completed["turn"]["final_output"] == "HELLO"
    assert completed["thread"]["turns"][-1]["final_output"] == "HELLO"


def test_api_streams_handled_unsupported_task_turn(tmp_path: Path):
    client = create_test_client(tmp_path)
    login_as_admin(client)

    thread = client.post("/api/v1/threads").json()
    with client.stream(
        "POST",
        f"/api/v1/threads/{thread['thread_id']}/tasks/stream",
        json={"task_text": "Summarize the latest stock market news"},
    ) as response:
        events = collect_sse_events(response)

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["turn"]["status"] == "unsupported"


def test_api_streams_visible_retry_before_success(tmp_path: Path):
    app = create_test_app(tmp_path)

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
    app.state.controller.tools["TextProcessorTool"] = flaky_tool
    client = TestClient(app)
    login_as_admin(client)

    thread = client.post("/api/v1/threads").json()
    with client.stream(
        "POST",
        f"/api/v1/threads/{thread['thread_id']}/tasks/stream",
        json={"task_text": 'Convert "hello" to uppercase'},
    ) as response:
        events = collect_sse_events(response)

    assert flaky_tool.calls == 2
    assert any(event["event"] == "retry_scheduled" for event in events)
    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["turn"]["final_output"] == "HELLO"
