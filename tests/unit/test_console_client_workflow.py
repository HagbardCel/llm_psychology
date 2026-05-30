from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
import trio


class _StubOutput:
    def __init__(self) -> None:
        self.user_messages: list[str] = []
        self.system_messages: list[str] = []
        self.errors: list[str] = []
        self.prompts: list[str] = []

    def system(self, message: str) -> None:
        self.system_messages.append(message)

    def prompt(self, message: str, **_kwargs: Any) -> None:
        self.prompts.append(message)

    def user_text(self, message: str, **_kwargs: Any) -> None:
        self.user_messages.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def log_chat(self, _role: str, _text: str) -> None:
        return None

    def log_input(self, _text: str) -> None:
        return None


pytestmark = [pytest.mark.trio, pytest.mark.unit]


@pytest.fixture
def console_client_cls(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repo_root / "console-ui"))
    module = importlib.import_module("src.console_client")
    yield module.ConsoleClient
    # Avoid leaking the generic `src` package into unrelated tests.
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)


async def test_console_assessment_recommendations_do_not_leak_api_instructions(
    console_client_cls,
):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
    )

    await client._handle_assessment_recommendations(
        {
            "recommendations": [
                {
                    "style_id": "cbt",
                    "score": 0.85,
                    "explanation": "Test explanation",
                }
            ]
        }
    )

    leaked = any(
        "POST /api/workflow/select_therapy_style" in message
        for message in output.user_messages
    )
    assert leaked is False


async def test_console_suppresses_duplicate_recommendation_display(console_client_cls):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
    )
    payload = {
        "recommendations": [
            {
                "style_id": "cbt",
                "score": 0.85,
                "explanation": "Test explanation",
            }
        ]
    }

    await client._handle_assessment_recommendations(payload)
    await client._handle_assessment_recommendations(payload)

    assert output.user_messages.count("🎯 ASSESSMENT RECOMMENDATIONS") == 1


async def test_console_websocket_wait_event_does_not_render_status(console_client_cls):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
    )

    await client._handle_workflow_next_action(
        {
            "required_action": "wait",
            "prompt": "Assessment in progress.",
            "state_signature": "wait_1",
        }
    )

    assert output.user_messages == []


async def test_console_workflow_event_does_not_complete_pending_chat_response(
    console_client_cls,
):
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=_StubOutput(),
    )
    client.waiting_for_response = True

    await client._handle_workflow_next_action(
        {"required_action": "wait", "state_signature": "wait_1"}
    )

    assert client.response_complete.is_set() is False


async def test_console_initial_greeting_completion_does_not_complete_pending_chat(
    console_client_cls,
):
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=_StubOutput(),
    )
    client.waiting_for_initial_message = True
    client.waiting_for_response = True

    await client._handle_chat_response_chunk({"chunk": "", "is_complete": True})

    assert client.session_ready.is_set() is True
    assert client.response_complete.is_set() is False


async def test_console_initial_greeting_timeout_keeps_chat_disabled(console_client_cls):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
    )
    client.waiting_for_initial_message = True

    ready = await client._await_session_ready(timeout_seconds=0)

    assert ready is False
    assert client.session_ready.is_set() is False
    assert output.errors == [
        "❌ Initial greeting did not finish in time. "
        "Chat remains disabled to avoid overlapping responses."
    ]


async def test_console_websocket_connection_uses_configured_origin(
    console_client_cls,
):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://api:8000",
        websocket_url="http://api:8000",
        websocket_origin="http://localhost:5173",
        user_id="console_user",
        output=output,
    )

    assert client._build_websocket_url() == "ws://api:8000/ws?user_id=console_user"
    assert client._websocket_headers() == [("Origin", "http://localhost:5173")]


async def test_console_websocket_origin_defaults_to_backend_url(
    console_client_cls,
):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000/ws",
        user_id="user-1",
        output=output,
    )

    assert client._build_websocket_url() == "ws://localhost:8000/ws?user_id=user-1"
    assert client._websocket_headers() == [("Origin", "http://localhost:8000")]


async def test_chat_loop_returns_to_workflow_when_action_not_chat(
    console_client_cls,
):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
    )
    client.current_session_id = "session-1"

    async def fake_get_next_action() -> dict[str, Any]:
        return {"required_action": "select_therapy_style"}

    client._get_next_action = fake_get_next_action  # type: ignore[method-assign]

    called_get_user_input = False

    async def fake_get_user_input(*_args: Any, **_kwargs: Any) -> str:
        nonlocal called_get_user_input
        called_get_user_input = True
        return "hello"

    client._get_user_input = fake_get_user_input  # type: ignore[method-assign]

    exit_console = await client._chat_loop(ws=None)
    assert exit_console is False
    assert called_get_user_input is False


async def test_chat_loop_discards_input_when_workflow_advances_before_send(
    console_client_cls,
):
    class Sink:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def emit(self, event: str, **fields: Any) -> None:
            self.events.append((event, fields))

    sink = Sink()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=_StubOutput(),
        event_sink=sink,
    )
    client.current_session_id = "session-1"
    actions = [
        {"required_action": "start_intake"},
        {"required_action": "wait"},
    ]

    async def fake_get_next_action() -> dict[str, Any]:
        return actions.pop(0)

    async def fake_get_user_input(*_args: Any, **_kwargs: Any) -> str:
        return "typed while workflow advanced"

    class FakeWebSocket:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def send_message(self, message: str) -> None:
            self.messages.append(message)

    client._get_next_action = fake_get_next_action  # type: ignore[method-assign]
    client._get_user_input = fake_get_user_input  # type: ignore[method-assign]
    ws = FakeWebSocket()

    assert await client._chat_loop(ws) is False
    assert ws.messages == []
    assert sink.events[-1] == (
        "discarded_input",
        {
            "reason": "workflow_advanced_before_send",
            "required_action": "wait",
        },
    )


async def test_select_therapy_style_posts_and_clears_pending_recommendations(
    console_client_cls,
):
    output = _StubOutput()
    class Sink:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def emit(self, event: str, **fields: Any) -> None:
            self.events.append((event, fields))

    sink = Sink()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
        event_sink=sink,
    )
    client.current_session_id = "session-1"
    client.pending_recommendations = [
        {"style_id": "cbt", "explanation": "Test explanation"},
        {"style_id": "freud", "explanation": "Another explanation"},
    ]

    async def fake_get_user_input(_prompt: str = "", _default: str | None = None) -> str:
        return "1"

    client._get_user_input = fake_get_user_input  # type: ignore[method-assign]

    api_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def fake_api_request(method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        api_calls.append((method, endpoint, kwargs))
        return {}

    client._api_request = fake_api_request  # type: ignore[method-assign]

    await client._select_therapy_style()

    assert api_calls == [
        (
            "POST",
            "/workflow/select_therapy_style",
            {
                "json": {
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "selected_therapy_style": "cbt",
                }
            },
        )
    ]
    assert client.pending_recommendations is None
    assert sink.events[-1] == (
        "therapy_style_selected",
        {"selected_therapy_style": "cbt", "session_id": "session-1"},
    )


async def test_follow_workflow_runs_style_selection_action(console_client_cls):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
    )
    client.current_session_id = "session-1"

    actions = [
        {"required_action": "select_therapy_style"},
        {"required_action": "error", "error": "stop"},
    ]

    async def fake_get_next_action() -> dict[str, Any]:
        return actions.pop(0)

    client._get_next_action = fake_get_next_action  # type: ignore[method-assign]

    called_select = False

    async def fake_select_therapy_style() -> None:
        nonlocal called_select
        called_select = True

    client._select_therapy_style = fake_select_therapy_style  # type: ignore[method-assign]

    called_chat_loop = False

    async def fake_chat_loop(_ws: Any) -> bool:
        nonlocal called_chat_loop
        called_chat_loop = True
        return False

    client._chat_loop = fake_chat_loop  # type: ignore[method-assign]

    await client._follow_workflow(ws=None)

    assert called_select is True
    assert called_chat_loop is False


async def test_follow_workflow_renders_same_wait_signature_once(
    console_client_cls, monkeypatch
):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
    )
    client.connected = True
    actions = [
        {
            "required_action": "wait",
            "prompt": "Assessment in progress.",
            "state_signature": "wait_1",
        },
        {
            "required_action": "wait",
            "prompt": "Assessment in progress.",
            "state_signature": "wait_1",
        },
        {"required_action": "error", "error": "stop"},
    ]

    async def fake_get_next_action() -> dict[str, Any]:
        return actions.pop(0)

    async def fake_sleep(_seconds: float) -> None:
        return None

    client._get_next_action = fake_get_next_action  # type: ignore[method-assign]
    monkeypatch.setattr(trio, "sleep", fake_sleep)

    await client._follow_workflow(ws=None)

    requested_wait = [
        message
        for message in output.user_messages
        if message.startswith("⏳ Backend requested wait:")
    ]
    assert requested_wait == ["⏳ Backend requested wait: Assessment in progress."]


async def test_follow_workflow_renders_wait_heartbeat_after_sixty_seconds(
    console_client_cls, monkeypatch
):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
    )
    client.connected = True
    actions = [
        {
            "required_action": "wait",
            "prompt": "Assessment in progress.",
            "state_signature": "wait_1",
        }
        for _ in range(31)
    ]
    actions.append({"required_action": "error", "error": "stop"})

    async def fake_get_next_action() -> dict[str, Any]:
        return actions.pop(0)

    async def fake_sleep(_seconds: float) -> None:
        return None

    client._get_next_action = fake_get_next_action  # type: ignore[method-assign]
    monkeypatch.setattr(trio, "sleep", fake_sleep)

    await client._follow_workflow(ws=None)

    heartbeats = [
        message
        for message in output.user_messages
        if message.startswith("⏳ Still waiting")
    ]
    assert heartbeats == [
        "⏳ Still waiting (60s elapsed): Assessment in progress."
    ]


async def test_request_end_session_waits_for_session_ended(console_client_cls):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
    )
    client.connected = True
    client.current_session_id = "session-1"

    class FakeWebSocket:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def send_message(self, message: str) -> None:
            self.messages.append(message)
            await client._handle_session_ended({"reason": "User ended session"})

    ws = FakeWebSocket()
    await client._request_end_session(ws, reason="User ended session")

    assert ws.messages
    assert client.session_end_requested is True


async def test_request_end_session_reports_timeout(console_client_cls):
    output = _StubOutput()
    client = console_client_cls(
        backend_url="http://localhost:8000",
        websocket_url="ws://localhost:8000",
        user_id="user-1",
        output=output,
    )
    client.connected = True
    client.current_session_id = "session-1"

    class FakeWebSocket:
        async def send_message(self, _message: str) -> None:
            return None

    with trio.fail_after(1):
        await client._request_end_session(
            FakeWebSocket(), reason="User ended session", timeout_seconds=0.01
        )

    assert any("not confirmed" in message for message in output.user_messages)
