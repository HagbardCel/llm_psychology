"""Unit tests for one-shot WebSocket chat adapter."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.datastructures import Headers

from jung.api.app import ApiState
from jung.api.settings import ApiSettings
from jung.api.websocket import _handle_chat_connection
from jung.config import build_settings
from jung.domain.models import Message, MessageRole
from jung.domain.results import ChatCompleted, ChatToken

pytestmark = pytest.mark.asyncio


def _default_settings(
    *,
    send_timeout: float = 5.0,
    close_timeout: float = 2.0,
    allowed_origins: tuple[str, ...] = (),
) -> ApiSettings:
    return ApiSettings(
        application=build_settings(
            database_path="data/jung.db",
            llm_base_url="http://127.0.0.1:8080/v1",
            llm_api_key="",
            default_model="local-model",
        ),
        allowed_origins=allowed_origins,
        websocket_send_timeout=send_timeout,
        websocket_close_timeout=close_timeout,
    )


class FakeWebSocket:
    def __init__(
        self,
        *,
        api_state: ApiState,
        api_settings: ApiSettings,
        headers: dict[str, str] | None = None,
    ) -> None:
        import asyncio

        self.headers = Headers(headers=headers or {})
        self.app = SimpleNamespace(
            state=SimpleNamespace(api=api_state, api_settings=api_settings)
        )
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.sent: list[dict[str, Any]] = []
        self._receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code

    async def receive(self) -> dict[str, Any]:
        return await self._receive_queue.get()

    def queue_disconnect(self) -> None:
        self._receive_queue.put_nowait({"type": "websocket.disconnect"})

    def queue_text(self, text: str) -> None:
        self._receive_queue.put_nowait({"type": "websocket.receive", "text": text})

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


@dataclass
class MockApplication:
    stream_message: Any = None


@dataclass
class MockRuntime:
    application: MockApplication


FIXED_INVALID_REQUEST_ID = uuid4()


@pytest.mark.parametrize(
    ("text_payload", "expected_request_id"),
    [
        ("not json", None),
        (
            json.dumps(
                {
                    "type": "send_message",
                    "request_id": str(FIXED_INVALID_REQUEST_ID),
                }
            ),
            FIXED_INVALID_REQUEST_ID,
        ),
        (
            json.dumps(
                {
                    "type": "unknown",
                    "request_id": str(FIXED_INVALID_REQUEST_ID),
                    "session_id": str(uuid4()),
                    "client_message_id": str(uuid4()),
                    "content": "secret-content",
                }
            ),
            FIXED_INVALID_REQUEST_ID,
        ),
    ],
)
async def test_invalid_inbound_produces_validation_error_and_closes(
    text_payload: str,
    expected_request_id: object,
) -> None:
    runtime = MockRuntime(application=MockApplication())
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_text(text_payload)

    await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    errors = [item for item in fake.sent if item.get("type") == "error"]
    assert len(errors) == 1
    dumped = json.dumps(errors[0])
    assert "secret-content" not in dumped
    assert errors[0]["error"]["code"] == "validation_error"
    actual = UUID(errors[0]["request_id"])
    if expected_request_id is not None:
        assert actual == expected_request_id
    assert fake.closed is True


async def test_one_shot_streams_tokens_then_completion_and_closes() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    now = datetime.now(UTC)
    user = Message(
        id=uuid4(),
        session_id=session_id,
        sequence=1,
        role=MessageRole.USER,
        content="hello",
        created_at=now,
        client_message_id=client_message_id,
    )
    assistant = Message(
        id=uuid4(),
        session_id=session_id,
        sequence=2,
        role=MessageRole.ASSISTANT,
        content="hi",
        created_at=now,
        client_message_id=client_message_id,
    )

    async def stream_message(_command) -> AsyncIterator[object]:
        yield ChatToken(
            session_id=session_id,
            client_message_id=client_message_id,
            request_id=request_id,
            text="hi",
        )
        yield ChatCompleted(
            session_id=session_id,
            client_message_id=client_message_id,
            request_id=request_id,
            user_message=user,
            assistant_message=assistant,
        )

    runtime = MockRuntime(application=MockApplication(stream_message=stream_message))
    fake = FakeWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_text(
        json.dumps(
            {
                "type": "send_message",
                "session_id": str(session_id),
                "client_message_id": str(client_message_id),
                "request_id": str(request_id),
                "content": "hello",
            }
        )
    )

    await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]

    types = [item["type"] for item in fake.sent]
    assert types == ["token", "message_completed"]
    assert "snapshot_changed" not in types
    assert "message_in_progress" not in types
    assert fake.sent[0]["request_id"] == str(request_id)
    assert fake.sent[0]["session_id"] == str(session_id)
    assert fake.sent[0]["client_message_id"] == str(client_message_id)
    assert fake.closed is True


async def test_send_disconnect_after_token_closes_stream() -> None:
    import asyncio

    from starlette.websockets import WebSocketDisconnect

    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    aclose_called = asyncio.Event()
    receive_cancelled = asyncio.Event()

    async def stream_message(_command) -> AsyncIterator[object]:
        try:
            yield ChatToken(
                session_id=session_id,
                client_message_id=client_message_id,
                request_id=request_id,
                text="hi",
            )
            await asyncio.Event().wait()
        finally:
            aclose_called.set()

    class DisconnectingWebSocket(FakeWebSocket):
        async def receive(self) -> dict[str, Any]:
            try:
                return await super().receive()
            except asyncio.CancelledError:
                receive_cancelled.set()
                raise

        async def send_json(self, data: dict[str, Any]) -> None:
            if data.get("type") == "token":
                raise WebSocketDisconnect()
            await super().send_json(data)

    runtime = MockRuntime(application=MockApplication(stream_message=stream_message))
    fake = DisconnectingWebSocket(
        api_state=ApiState(runtime=runtime, ready=True),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_text(
        json.dumps(
            {
                "type": "send_message",
                "session_id": str(session_id),
                "client_message_id": str(client_message_id),
                "request_id": str(request_id),
                "content": "hello",
            }
        )
    )

    await _handle_chat_connection(fake, runtime, _default_settings())  # type: ignore[arg-type]
    assert aclose_called.is_set()
    assert receive_cancelled.is_set()


async def test_fresh_cancellation_during_active_stream_cleanup_propagates() -> None:
    import asyncio

    from jung._async_cleanup import close_awaitable_safely, drain_cancelled_task

    drain_started = asyncio.Event()
    drain_release = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def slow_owned_task() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            drain_started.set()
            await drain_release.wait()
            raise

    preserve_cleanup_cancellation = False

    async def run_normal_then_cancel_during_cleanup() -> None:
        nonlocal preserve_cleanup_cancellation
        owned = asyncio.create_task(slow_owned_task())
        try:
            return
        except asyncio.CancelledError:
            preserve_cleanup_cancellation = True
            raise
        finally:

            async def cleanup() -> None:
                if not owned.done():
                    owned.cancel()
                await drain_cancelled_task(owned)
                cleanup_finished.set()

            await close_awaitable_safely(
                cleanup,
                record_failure=lambda _exc: None,
                preserve_existing_cancellation=preserve_cleanup_cancellation,
            )

    task = asyncio.create_task(run_normal_then_cancel_during_cleanup())
    await drain_started.wait()
    task.cancel("cleanup-cancel")
    await asyncio.sleep(0)
    assert not task.done()
    drain_release.set()
    with pytest.raises(asyncio.CancelledError) as exc_info:
        await task
    assert exc_info.value.args == ("cleanup-cancel",)
    assert cleanup_finished.is_set()
