from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest


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


async def test_select_therapy_style_posts_and_clears_pending_recommendations(
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
