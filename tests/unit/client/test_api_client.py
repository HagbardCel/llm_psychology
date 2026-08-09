from __future__ import annotations

import asyncio
import json
import math
import traceback
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from websockets.exceptions import ConnectionClosed

from jung.api.contracts import (
    AppSnapshotResponse,
    ErrorCode,
    ErrorEnvelope,
    HealthResponse,
    MessageResponse,
    OperationSummaryResponse,
    SendMessageCommand,
    SessionDetailResponse,
    SessionHistoryResponse,
)
from jung.client.api_client import (
    _ALLOWED_HTTP_ERROR_STATUSES,
    ClientSettings,
    JungApiClient,
    JungApiError,
    JungChatConnection,
    JungConnectionClosed,
    JungProtocolError,
    JungTransportError,
    ProtocolErrorKind,
)


def _snapshot() -> AppSnapshotResponse:
    return AppSnapshotResponse(
        stage="intake",
        profile_complete=True,
        available_commands=["send_message"],
    )


def _message(
    *,
    session_id: UUID,
    client_message_id: UUID,
    role: str,
    content: str,
    sequence: int,
) -> MessageResponse:
    return MessageResponse(
        id=uuid4(),
        session_id=session_id,
        sequence=sequence,
        role=role,  # type: ignore[arg-type]
        content=content,
        created_at=datetime.now(UTC),
        client_message_id=client_message_id,
    )


def _history(
    *,
    session_id: UUID,
    client_message_id: UUID,
    user_contents: tuple[str, ...] = (),
    assistant_contents: tuple[str, ...] = (),
) -> SessionHistoryResponse:
    messages = [
        _message(
            session_id=session_id,
            client_message_id=client_message_id,
            role="user",
            content=content,
            sequence=index,
        )
        for index, content in enumerate(user_contents, start=1)
    ]
    messages.extend(
        _message(
            session_id=session_id,
            client_message_id=client_message_id,
            role="assistant",
            content=content,
            sequence=index,
        )
        for index, content in enumerate(
            assistant_contents,
            start=len(messages) + 1,
        )
    )
    return SessionHistoryResponse(
        session=SessionDetailResponse(
            id=session_id,
            kind="intake",
            started_at=datetime.now(UTC),
        ),
        messages=messages,
        plans=[],
    )


def _client_with_handler(
    handler,
    *,
    base_url: str = "http://localhost:8000",
) -> JungApiClient:
    return JungApiClient(
        ClientSettings(base_url),
        transport=httpx.MockTransport(handler),
    )


def _command(*, content: str = "hello") -> SendMessageCommand:
    return SendMessageCommand(
        type="send_message",
        request_id=uuid4(),
        session_id=uuid4(),
        client_message_id=uuid4(),
        content=content,
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://localhost:8000",
        "http://user:password@localhost:8000",
        "http://localhost:8000/service",
        "http://localhost:8000?query=yes",
        "http://localhost:8000#fragment",
        "http://localhost:8000?",
        "http://localhost:8000#",
        "http://localhost:8000/?",
        "http://localhost:8000/#",
    ],
)
def test_client_settings_reject_non_origin_urls_without_echoing_them(
    base_url: str,
) -> None:
    with pytest.raises(ValueError) as raised:
        ClientSettings(base_url)
    assert base_url not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("base_url", (None, 42, object()))
def test_client_settings_reject_non_string_origins(base_url: object) -> None:
    with pytest.raises(ValueError) as raised:
        ClientSettings(base_url)  # type: ignore[arg-type]
    assert str(raised.value) == "base_url must be a valid HTTP(S) origin"
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("value", [0, -1, math.inf, -math.inf, math.nan, True])
def test_client_settings_reject_invalid_timeouts(value: float) -> None:
    with pytest.raises(ValueError):
        ClientSettings("http://localhost:8000", transport_timeout=value)


@pytest.mark.asyncio
async def test_new_message_command_ids_have_distinct_lifetimes() -> None:
    async with JungApiClient(ClientSettings("https://localhost:8443")) as client:
        session_id = uuid4()
        retained_id = uuid4()
        first = client.new_message_command(
            session_id,
            "hello",
            client_message_id=retained_id,
        )
        second = client.new_message_command(
            session_id,
            "hello",
            client_message_id=retained_id,
        )
        generated = client.new_message_command(session_id, "hello")

        assert first.client_message_id == second.client_message_id == retained_id
        assert first.request_id != second.request_id
        assert generated.client_message_id != retained_id
        assert not hasattr(first, "expected" + "_revision")


@pytest.mark.asyncio
async def test_start_end_retry_send_no_http_body() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        request_id = request.headers["X-Request-ID"]
        if request.url.path.endswith("/sessions") and request.method == "POST":
            session_id = str(uuid4())
            return httpx.Response(
                201,
                headers={"X-Request-ID": request_id},
                json={
                    "session": {
                        "id": session_id,
                        "kind": "therapy",
                        "started_at": "2026-01-01T00:00:00Z",
                    },
                    "snapshot": {
                        "stage": "therapy",
                        "profile_complete": True,
                        "active_session": {
                            "id": session_id,
                            "kind": "therapy",
                            "started_at": "2026-01-01T00:00:00Z",
                        },
                        "available_commands": ["end_session", "send_message"],
                    },
                },
            )
        if "/end" in request.url.path:
            return httpx.Response(
                202,
                headers={"X-Request-ID": request_id},
                json={
                    "stage": "post_session",
                    "profile_complete": True,
                    "available_commands": [],
                },
            )
        if request.url.path.endswith("/operations/current/retry"):
            return httpx.Response(
                202,
                headers={"X-Request-ID": request_id},
                json={
                    "stage": "assessment",
                    "profile_complete": True,
                    "available_commands": [],
                },
            )
        raise AssertionError(f"unexpected request {request.method} {request.url.path}")

    client = _client_with_handler(handler)
    started = await client.start_session()
    await client.end_session(started.session.id)
    await client.retry_current_operation()
    await client.aclose()

    assert len(captured) == 3
    for request in captured:
        assert request.content == b""


@pytest.mark.asyncio
async def test_http_success_and_api_error_are_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        request_id = request.headers["X-Request-ID"]
        if request.url.path.endswith("/health"):
            return httpx.Response(
                200,
                headers={"X-Request-ID": request_id},
                json={"status": "healthy"},
            )
        return httpx.Response(
            503,
            headers={"X-Request-ID": request_id},
            json={
                "code": "not_ready",
                "message": "Service is not ready",
                "request_id": request_id,
                "retryable": True,
            },
        )

    client = _client_with_handler(handler)
    assert await client.get_health() == HealthResponse(status="healthy")
    with pytest.raises(JungApiError) as raised:
        await client.get_state()
    assert raised.value.status == 503
    assert raised.value.code == "not_ready"
    assert "Service is not ready" not in str(raised.value)
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header", "kind"),
    [
        (None, ProtocolErrorKind.MISSING_REQUEST_ID),
        ("not-a-uuid", ProtocolErrorKind.MALFORMED_REQUEST_ID),
        (str(uuid4()), ProtocolErrorKind.REQUEST_ID_MISMATCH),
    ],
)
async def test_http_request_id_header_is_strict(
    header: str | None,
    kind: ProtocolErrorKind,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        headers = {} if header is None else {"X-Request-ID": header}
        return httpx.Response(200, headers=headers, json={"status": "healthy"})

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_health()
    assert raised.value.kind is kind
    await client.aclose()


@pytest.mark.asyncio
async def test_wrong_success_status_is_protocol_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            headers={"X-Request-ID": request.headers["X-Request-ID"]},
            json={"status": "healthy"},
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_health()
    assert raised.value.kind is ProtocolErrorKind.UNEXPECTED_STATUS
    await client.aclose()


@pytest.mark.asyncio
async def test_error_body_request_id_must_match_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            headers={"X-Request-ID": request.headers["X-Request-ID"]},
            json={
                "code": "not_ready",
                "message": "Service is not ready",
                "request_id": str(uuid4()),
                "retryable": True,
            },
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_health()
    assert raised.value.kind is ProtocolErrorKind.REQUEST_ID_MISMATCH
    await client.aclose()


@pytest.mark.asyncio
async def test_nested_error_envelope_request_id_must_match_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        snapshot = _snapshot().model_copy(
            update={
                "operation": OperationSummaryResponse(
                    id=uuid4(),
                    kind="assessment",
                    status="failed",
                    error=ErrorEnvelope(
                        code="llm_timeout",
                        message="Generation timed out",
                        request_id=uuid4(),
                        retryable=True,
                    ),
                )
            }
        )
        return httpx.Response(
            200,
            headers={"X-Request-ID": request.headers["X-Request-ID"]},
            content=snapshot.model_dump_json(),
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_state()
    assert raised.value.kind is ProtocolErrorKind.REQUEST_ID_MISMATCH
    await client.aclose()


@pytest.mark.asyncio
async def test_invalid_body_diagnostics_do_not_retain_secret_content() -> None:
    secret = "private therapy disclosure"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"X-Request-ID": request.headers["X-Request-ID"]},
            json={"status": secret},
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_health()
    error = raised.value
    formatted = "".join(traceback.format_exception(error))
    assert error.kind is ProtocolErrorKind.INVALID_RESPONSE_BODY
    assert secret not in str(error)
    assert secret not in repr(error)
    assert secret not in formatted
    assert error.__cause__ is None
    await client.aclose()


@pytest.mark.asyncio
async def test_invalid_websocket_frame_diagnostics_are_sanitized() -> None:
    secret = "private websocket disclosure"

    class FakeWebSocket:
        async def send(self, _payload: str) -> None:
            return None

        async def recv(self):
            return f'{{"type":"token","text":"{secret}"'

        async def close(self):
            return None

    chat = JungChatConnection(FakeWebSocket())  # type: ignore[arg-type]
    stream = chat.stream(_command())
    with pytest.raises(JungProtocolError) as raised:
        await anext(stream)
    error = raised.value
    formatted = "".join(traceback.format_exception(error))
    assert error.kind is ProtocolErrorKind.INVALID_WEBSOCKET_FRAME
    assert secret not in str(error)
    assert secret not in repr(error)
    assert secret not in formatted
    assert error.__cause__ is None
    await chat.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("send", "receive"))
async def test_transport_failure_makes_chat_unusable_and_still_closes(
    operation: str,
) -> None:
    class FailingWebSocket:
        def __init__(self) -> None:
            self.close = AsyncMock()

        async def send(self, _payload: str) -> None:
            raise OSError("transport failed")

        async def recv(self) -> str:
            raise OSError("transport failed")

    websocket = FailingWebSocket()
    chat = JungChatConnection(websocket)  # type: ignore[arg-type]
    command = _command()

    stream = chat.stream(command)
    with pytest.raises(JungTransportError):
        if operation == "send":
            await anext(stream)
        else:
            # Force receive path after a successful send.
            websocket.send = AsyncMock()  # type: ignore[method-assign]
            await anext(stream)

    with pytest.raises(RuntimeError):
        await anext(chat.stream(command))
    await chat.aclose()
    await chat.aclose()
    websocket.close.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("send", "receive"))
async def test_remote_closure_makes_chat_unusable_and_still_closes(
    operation: str,
) -> None:
    class RemoteClosedWebSocket:
        def __init__(self) -> None:
            self.close = AsyncMock()

        async def send(self, _payload: str) -> None:
            raise ConnectionClosed(None, None, None)

        async def recv(self) -> str:
            raise ConnectionClosed(None, None, None)

    websocket = RemoteClosedWebSocket()
    chat = JungChatConnection(websocket)  # type: ignore[arg-type]
    command = _command()

    stream = chat.stream(command)
    with pytest.raises(JungConnectionClosed):
        if operation == "send":
            await anext(stream)
        else:
            websocket.send = AsyncMock()  # type: ignore[method-assign]
            await anext(stream)

    with pytest.raises(RuntimeError):
        await anext(chat.stream(command))
    await chat.aclose()
    await chat.aclose()
    websocket.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_explicit_chat_close_makes_connection_unusable() -> None:
    websocket = SimpleNamespace(close=AsyncMock())
    chat = JungChatConnection(websocket)  # type: ignore[arg-type]
    command = _command()

    await chat.aclose()
    await chat.aclose()
    with pytest.raises(RuntimeError):
        await anext(chat.stream(command))
    websocket.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_chat_close_retries_after_cancellation() -> None:
    close_attempts = 0

    class CancellingWebSocket:
        async def close(self) -> None:
            nonlocal close_attempts
            close_attempts += 1
            if close_attempts == 1:
                raise asyncio.CancelledError

    websocket = CancellingWebSocket()
    chat = JungChatConnection(websocket)  # type: ignore[arg-type]
    command = _command()

    with pytest.raises(asyncio.CancelledError):
        await chat.aclose()

    with pytest.raises(RuntimeError, match="chat connection is unusable"):
        await anext(chat.stream(command))

    await chat.aclose()
    assert close_attempts == 2

    await chat.aclose()
    assert close_attempts == 2


@pytest.mark.asyncio
async def test_second_stream_on_same_connection_raises_runtime_error() -> None:
    class ScriptedWebSocket:
        def __init__(self) -> None:
            self.close = AsyncMock()
            self._sent = False

        async def send(self, _payload: str) -> None:
            self._sent = True

        async def recv(self) -> str:
            command = _command()
            # unreachable; stream ends after terminal event below
            return (
                '{"type":"error","request_id":"'
                + str(command.request_id)
                + '","error":{"code":"validation_error","message":"bad",'
                + '"request_id":"'
                + str(command.request_id)
                + '"}}'
            )

    # Use a fixed command so the terminal error request_id matches if needed.
    request_id = uuid4()
    session_id = uuid4()
    client_message_id = uuid4()
    command = SendMessageCommand(
        type="send_message",
        request_id=request_id,
        session_id=session_id,
        client_message_id=client_message_id,
        content="hello",
    )

    class TerminalWebSocket:
        def __init__(self) -> None:
            self.close = AsyncMock()

        async def send(self, _payload: str) -> None:
            return None

        async def recv(self) -> str:
            return (
                '{"type":"error","request_id":"'
                + str(request_id)
                + '","error":{"code":"validation_error","message":"bad",'
                + '"request_id":"'
                + str(request_id)
                + '"}}'
            )

    chat = JungChatConnection(TerminalWebSocket())  # type: ignore[arg-type]
    events = [event async for event in chat.stream(command)]
    assert len(events) == 1

    # Terminal event marks the connection unusable; a second stream must fail.
    with pytest.raises(
        RuntimeError, match="chat connection (already used|is unusable)"
    ):
        await anext(chat.stream(_command()))

    # Fresh connection: mark used without consuming a terminal event.
    class NeverRecvWebSocket:
        def __init__(self) -> None:
            self.close = AsyncMock()
            self._sent = False

        async def send(self, _payload: str) -> None:
            self._sent = True

        async def recv(self) -> str:
            await asyncio.sleep(3600)
            raise AssertionError("unreachable")

    chat2 = JungChatConnection(NeverRecvWebSocket())  # type: ignore[arg-type]
    stream1 = chat2.stream(command)
    recv_task = asyncio.create_task(anext(stream1))
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="chat connection already used"):
        await anext(chat2.stream(_command()))
    recv_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await recv_task
    await chat.aclose()
    await chat2.aclose()


def test_allowed_http_error_statuses_are_exact_subset() -> None:
    assert _ALLOWED_HTTP_ERROR_STATUSES == {
        "invalid_command": frozenset({409}),
        "busy": frozenset({409}),
        "not_found": frozenset({404}),
        "validation_error": frozenset({422}),
        "internal_error": frozenset({500}),
        "not_ready": frozenset({503}),
    }
    wire_codes = set(get_args(ErrorCode))
    assert set(_ALLOWED_HTTP_ERROR_STATUSES) <= wire_codes
    for excluded in (
        "llm_unavailable",
        "llm_timeout",
        "invalid_llm_output",
        "operation_failed",
    ):
        assert excluded in wire_codes
        assert excluded not in _ALLOWED_HTTP_ERROR_STATUSES


@pytest.mark.asyncio
async def test_error_status_code_mismatch_raises_protocol_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        request_id = request.headers["X-Request-ID"]
        return httpx.Response(
            500,
            headers={"X-Request-ID": request_id},
            json={
                "code": "invalid_command",
                "message": "not allowed",
                "request_id": request_id,
                "retryable": False,
            },
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_state()
    assert raised.value.kind is ProtocolErrorKind.ERROR_STATUS_CODE_MISMATCH
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_code",
    ["llm_timeout", "operation_failed"],
)
async def test_stored_llm_failure_codes_are_not_http_mapped(
    error_code: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        request_id = request.headers["X-Request-ID"]
        return httpx.Response(
            409,
            headers={"X-Request-ID": request_id},
            json={
                "code": error_code,
                "message": "Generation failed",
                "request_id": request_id,
                "retryable": True,
            },
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_state()
    assert raised.value.kind is ProtocolErrorKind.ERROR_STATUS_CODE_MISMATCH
    await client.aclose()


@pytest.mark.asyncio
async def test_fresh_internal_error_accepts_500_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        request_id = request.headers["X-Request-ID"]
        return httpx.Response(
            500,
            headers={"X-Request-ID": request_id},
            json={
                "code": "internal_error",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
                "retryable": False,
            },
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungApiError) as raised:
        await client.get_state()
    assert raised.value.status == 500
    assert raised.value.code == "internal_error"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "expected_kind"),
    [
        (
            lambda event, command: {
                **event,
                "request_id": str(uuid4()),
            },
            ProtocolErrorKind.REQUEST_ID_MISMATCH,
        ),
        (
            lambda event, command: {
                **event,
                "session_id": str(uuid4()),
            },
            ProtocolErrorKind.INVALID_SERVER_EVENT,
        ),
        (
            lambda event, command: {
                **event,
                "client_message_id": str(uuid4()),
            },
            ProtocolErrorKind.INVALID_SERVER_EVENT,
        ),
    ],
)
async def test_chat_stream_rejects_mismatched_event_ids(
    mutate,
    expected_kind: ProtocolErrorKind,
) -> None:
    command = _command()
    token_payload = {
        "type": "token",
        "text": "hi",
        "request_id": str(command.request_id),
        "session_id": str(command.session_id),
        "client_message_id": str(command.client_message_id),
    }
    payload = mutate(token_payload, command)

    class FakeWebSocket:
        async def send(self, _payload: str) -> None:
            return None

        async def recv(self) -> str:
            return json.dumps(payload)

        async def close(self) -> None:
            return None

    chat = JungChatConnection(FakeWebSocket())  # type: ignore[arg-type]
    with pytest.raises(JungProtocolError) as raised:
        await anext(chat.stream(command))
    assert raised.value.kind is expected_kind
    summary = str(raised.value)
    assert str(command.request_id) not in summary
    assert str(command.session_id) not in summary
    assert str(command.client_message_id) not in summary
    await chat.aclose()
