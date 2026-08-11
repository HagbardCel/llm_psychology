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
from jung.api.websocket import _handle_chat_connection
from jung.config import JungSettings
from jung.domain.models import Message, MessageRole
from jung.domain.results import ChatCompleted, ChatToken
from tests.support.settings import make_test_settings

pytestmark = pytest.mark.asyncio


def _default_settings(
    *,
    send_timeout: float = 5.0,
    close_timeout: float = 2.0,
    allowed_origins: tuple[str, ...] = (),
) -> JungSettings:
    return make_test_settings(
        api_allowed_origins=allowed_origins,
        websocket_send_timeout=send_timeout,
        websocket_close_timeout=close_timeout,
    )


class FakeWebSocket:
    def __init__(
        self,
        *,
        api_state: ApiState,
        api_settings: JungSettings,
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
    application = MockApplication()
    fake = FakeWebSocket(
        api_state=ApiState(application=application),  # type: ignore[arg-type]
        api_settings=_default_settings(),
    )
    fake.queue_text(text_payload)

    await _handle_chat_connection(fake, application, _default_settings())  # type: ignore[arg-type]

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

    application = MockApplication(stream_message=stream_message)
    fake = FakeWebSocket(
        api_state=ApiState(application=application),  # type: ignore[arg-type]
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

    await _handle_chat_connection(fake, application, _default_settings())  # type: ignore[arg-type]

    types = [item["type"] for item in fake.sent]
    assert types == ["token", "message_completed"]
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

    application = MockApplication(stream_message=stream_message)
    fake = DisconnectingWebSocket(
        api_state=ApiState(application=application),  # type: ignore[arg-type]
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

    await _handle_chat_connection(fake, application, _default_settings())  # type: ignore[arg-type]
    assert aclose_called.is_set()
    assert receive_cancelled.is_set()


@pytest.mark.parametrize(
    "race",
    ["stream_pending", "stream_terminal_already_done"],
)
async def test_active_protocol_abort_closes_without_terminal_event(
    race: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

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
    stream_closed = asyncio.Event()
    terminal_produced = asyncio.Event()
    second_payload = json.dumps(
        {
            "type": "send_message",
            "session_id": str(session_id),
            "client_message_id": str(uuid4()),
            "request_id": str(uuid4()),
            "content": "illegal-second-frame",
        }
    )
    first_payload = json.dumps(
        {
            "type": "send_message",
            "session_id": str(session_id),
            "client_message_id": str(client_message_id),
            "request_id": str(request_id),
            "content": "hello",
        }
    )

    if race == "stream_pending":

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
                stream_closed.set()

        class ProtocolAbortWebSocket(FakeWebSocket):
            async def send_json(self, data: dict[str, Any]) -> None:
                if data.get("type") == "token":
                    await super().send_json(data)
                    self.queue_text(second_payload)
                    return
                await super().send_json(data)

            async def close(self, code: int = 1000) -> None:
                assert stream_closed.is_set()
                await super().close(code=code)

        application = MockApplication(stream_message=stream_message)
        fake = ProtocolAbortWebSocket(
            api_state=ApiState(application=application),  # type: ignore[arg-type]
            api_settings=_default_settings(),
        )
        fake.queue_text(first_payload)
        await _handle_chat_connection(fake, application, _default_settings())  # type: ignore[arg-type]
    else:

        async def stream_message(_command) -> AsyncIterator[object]:
            try:
                terminal_produced.set()
                yield ChatCompleted(
                    session_id=session_id,
                    client_message_id=client_message_id,
                    request_id=request_id,
                    user_message=user,
                    assistant_message=assistant,
                )
            finally:
                stream_closed.set()

        class ProtocolAbortWebSocket(FakeWebSocket):
            async def close(self, code: int = 1000) -> None:
                assert stream_closed.is_set()
                await super().close(code=code)

        application = MockApplication(stream_message=stream_message)
        fake = ProtocolAbortWebSocket(
            api_state=ApiState(application=application),  # type: ignore[arg-type]
            api_settings=_default_settings(),
        )
        fake.queue_text(first_payload)
        fake.queue_text(second_payload)

        real_wait = asyncio.wait

        async def wait_both_ws_tasks(fs, *args, **kwargs):  # noqa: ANN001
            tasks = set(fs)
            names = {task.get_name() for task in tasks}
            if names == {"ws-receive", "ws-stream"}:
                done, pending = await real_wait(
                    tasks,
                    return_when=asyncio.ALL_COMPLETED,
                )
                assert not pending
                assert terminal_produced.is_set()
                return done, pending
            return await real_wait(fs, *args, **kwargs)

        monkeypatch.setattr(asyncio, "wait", wait_both_ws_tasks)
        await _handle_chat_connection(fake, application, _default_settings())  # type: ignore[arg-type]

    assert stream_closed.is_set()
    assert fake.closed is True
    types = [item["type"] for item in fake.sent]
    assert "message_completed" not in types
    assert "message_failed" not in types
    assert "error" not in types
    if race == "stream_pending":
        assert types == ["token"]
    else:
        assert types == []
        assert terminal_produced.is_set()


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
