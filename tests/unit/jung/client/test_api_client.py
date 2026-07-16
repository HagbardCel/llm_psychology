from __future__ import annotations

import asyncio
import math
import traceback
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError
from websockets.exceptions import ConnectionClosed

from jung.api.contracts import (
    AppSnapshotResponse,
    ChatTurnSummaryResponse,
    ErrorEnvelope,
    ErrorEvent,
    HealthResponse,
    MessageCompletedEvent,
    MessageInProgressEvent,
    MessageResponse,
    OperationSummaryResponse,
    SendMessageCommand,
    SessionDetailResponse,
    SessionHistoryResponse,
)
from jung.client.api_client import (
    ChatReconciliationResult,
    ChatReconciliationStatus,
    ClientSettings,
    JungApiClient,
    JungApiError,
    JungChatConnection,
    JungConnectionClosed,
    JungProtocolError,
    JungTransportError,
    ProtocolErrorKind,
)


def _snapshot(
    *,
    pending: ChatTurnSummaryResponse | None = None,
    revision: int = 1,
) -> AppSnapshotResponse:
    return AppSnapshotResponse(
        revision=revision,
        stage="intake",
        profile_complete=True,
        active_chat_turn=pending,
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
        role=role,
        content=content,
        created_at=datetime.now(UTC),
        client_message_id=client_message_id,
    )


def _turn(*, session_id: UUID, client_message_id: UUID) -> ChatTurnSummaryResponse:
    return ChatTurnSummaryResponse(
        id=uuid4(),
        session_id=session_id,
        client_message_id=client_message_id,
        status="pending",
        user_message_id=uuid4(),
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


async def _install_transport(client: JungApiClient, handler) -> None:
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=client._base_url,
        timeout=client.settings.transport_timeout,
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
    with pytest.raises(ValueError):
        ClientSettings("http://localhost:8000", acknowledgement_timeout=value)


@pytest.mark.asyncio
async def test_client_lifecycle_and_idempotent_close() -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000/"))
    close = AsyncMock()
    client._http = SimpleNamespace(aclose=close)

    async with client as entered:
        assert entered is client

    await client.aclose()
    close.assert_awaited_once_with()
    with pytest.raises(RuntimeError):
        await client.get_health()
    with pytest.raises(RuntimeError):
        async with client.open_chat():
            pass
    intent = client.new_chat_intent(uuid4(), "hello")
    with pytest.raises(RuntimeError):
        await client.reconcile_chat_turn(intent)


@pytest.mark.asyncio
async def test_intent_and_attempt_ids_have_distinct_lifetimes() -> None:
    async with JungApiClient(ClientSettings("https://localhost:8443")) as client:
        session_id = uuid4()
        retained_id = uuid4()
        retained = client.new_chat_intent(
            session_id,
            "hello",
            client_message_id=retained_id,
        )
        generated = client.new_chat_intent(session_id, "hello")
        first = client.new_message_command(retained, expected_revision=7)
        second = client.new_message_command(retained, expected_revision=8)

        assert retained.client_message_id == retained_id
        assert generated.client_message_id != retained_id
        assert first.client_message_id == second.client_message_id == retained_id
        assert first.request_id != second.request_id
        assert first.expected_revision == 7
        assert second.expected_revision == 8
        assert client._websocket_url() == "wss://localhost:8443/api/v1/chat"


@pytest.mark.asyncio
async def test_http_success_and_api_error_are_typed() -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))

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

    await _install_transport(client, handler)
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
    client = JungApiClient(ClientSettings("http://localhost:8000"))

    def handler(_request: httpx.Request) -> httpx.Response:
        headers = {} if header is None else {"X-Request-ID": header}
        return httpx.Response(200, headers=headers, json={"status": "healthy"})

    await _install_transport(client, handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_health()
    assert raised.value.kind is kind
    await client.aclose()


@pytest.mark.asyncio
async def test_wrong_success_status_is_protocol_error() -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            headers={"X-Request-ID": request.headers["X-Request-ID"]},
            json={"status": "healthy"},
        )

    await _install_transport(client, handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_health()
    assert raised.value.kind is ProtocolErrorKind.UNEXPECTED_STATUS
    await client.aclose()


@pytest.mark.asyncio
async def test_error_body_request_id_must_match_header() -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))

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

    await _install_transport(client, handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_health()
    assert raised.value.kind is ProtocolErrorKind.REQUEST_ID_MISMATCH
    await client.aclose()


@pytest.mark.asyncio
async def test_nested_error_envelope_request_id_must_match_header() -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))

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

    await _install_transport(client, handler)
    with pytest.raises(JungProtocolError) as raised:
        await client.get_state()
    assert raised.value.kind is ProtocolErrorKind.REQUEST_ID_MISMATCH
    await client.aclose()


@pytest.mark.asyncio
async def test_invalid_body_diagnostics_do_not_retain_secret_content() -> None:
    secret = "private therapy disclosure"
    client = JungApiClient(ClientSettings("http://localhost:8000"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"X-Request-ID": request.headers["X-Request-ID"]},
            json={"status": secret},
        )

    await _install_transport(client, handler)
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
        async def recv(self):
            return f'{{"type":"token","text":"{secret}"'

        async def close(self):
            return None

    chat = JungChatConnection(FakeWebSocket())
    events = chat.events()
    with pytest.raises(JungProtocolError) as raised:
        await anext(events)
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
    chat = JungChatConnection(websocket)
    command = SendMessageCommand(
        type="send_message",
        request_id=uuid4(),
        expected_revision=1,
        session_id=uuid4(),
        client_message_id=uuid4(),
        content="hello",
    )

    if operation == "send":
        with pytest.raises(JungTransportError):
            await chat.send(command)
    else:
        events = chat.events()
        with pytest.raises(JungTransportError):
            await anext(events)

    with pytest.raises(RuntimeError):
        await chat.send(command)
    with pytest.raises(RuntimeError):
        await anext(chat.events())
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
    chat = JungChatConnection(websocket)
    command = SendMessageCommand(
        type="send_message",
        request_id=uuid4(),
        expected_revision=1,
        session_id=uuid4(),
        client_message_id=uuid4(),
        content="hello",
    )

    if operation == "send":
        with pytest.raises(JungConnectionClosed):
            await chat.send(command)
    else:
        events = chat.events()
        with pytest.raises(JungConnectionClosed):
            await anext(events)

    with pytest.raises(RuntimeError):
        await chat.send(command)
    with pytest.raises(RuntimeError):
        await anext(chat.events())
    await chat.aclose()
    await chat.aclose()
    websocket.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_explicit_chat_close_makes_connection_unusable() -> None:
    websocket = SimpleNamespace(close=AsyncMock())
    chat = JungChatConnection(websocket)
    command = SendMessageCommand(
        type="send_message",
        request_id=uuid4(),
        expected_revision=1,
        session_id=uuid4(),
        client_message_id=uuid4(),
        content="hello",
    )

    await chat.aclose()
    await chat.aclose()
    with pytest.raises(RuntimeError):
        await chat.send(command)
    with pytest.raises(RuntimeError):
        await anext(chat.events())
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

    with pytest.raises(asyncio.CancelledError):
        await chat.aclose()

    assert chat._unusable is True
    assert chat._close_attempted is False

    await chat.aclose()
    assert close_attempts == 2

    await chat.aclose()
    assert close_attempts == 2


@pytest.mark.asyncio
async def test_classification_complete_pending_conflict_and_unresolved() -> None:
    async with JungApiClient(ClientSettings("http://localhost:8000")) as client:
        session_id = uuid4()
        client_message_id = uuid4()
        intent = client.new_chat_intent(
            session_id,
            "original",
            client_message_id=client_message_id,
        )
        complete = client._classify_chat_state(
            intent,
            _snapshot(),
            _history(
                session_id=session_id,
                client_message_id=client_message_id,
                user_contents=("original",),
                assistant_contents=("reply",),
            ),
        )
        assert complete is not None
        assert complete.status is ChatReconciliationStatus.COMPLETE

        user_message_id = uuid4()
        pending_turn = ChatTurnSummaryResponse(
            id=uuid4(),
            session_id=session_id,
            client_message_id=client_message_id,
            status="pending",
            user_message_id=user_message_id,
        )
        pending = client._classify_chat_state(
            intent,
            _snapshot(pending=pending_turn),
            _history(
                session_id=session_id,
                client_message_id=client_message_id,
                user_contents=("original",),
            ),
        )
        assert pending is not None
        assert pending.status is ChatReconciliationStatus.IN_PROGRESS

        conflict = client._classify_chat_state(
            intent,
            _snapshot(),
            _history(
                session_id=session_id,
                client_message_id=client_message_id,
                user_contents=("different",),
                assistant_contents=("unrelated reply",),
            ),
        )
        assert conflict is not None
        assert conflict.status is ChatReconciliationStatus.IDENTITY_CONFLICT

        unresolved = client._classify_chat_state(
            intent,
            _snapshot(),
            _history(
                session_id=session_id,
                client_message_id=client_message_id,
            ),
        )
        assert unresolved is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("users", "assistants"),
    [
        ((), ("reply",)),
        (("original", "original"), ()),
        (("original",), ("reply", "reply")),
    ],
)
async def test_impossible_histories_raise_protocol_error(
    users: tuple[str, ...],
    assistants: tuple[str, ...],
) -> None:
    async with JungApiClient(ClientSettings("http://localhost:8000")) as client:
        session_id = uuid4()
        client_message_id = uuid4()
        intent = client.new_chat_intent(
            session_id,
            "original",
            client_message_id=client_message_id,
        )
        with pytest.raises(JungProtocolError) as raised:
            client._classify_chat_state(
                intent,
                _snapshot(),
                _history(
                    session_id=session_id,
                    client_message_id=client_message_id,
                    user_contents=users,
                    assistant_contents=assistants,
                ),
            )
        assert raised.value.kind is ProtocolErrorKind.IMPOSSIBLE_HISTORY


@pytest.mark.asyncio
async def test_durable_failure_requires_turn_identity() -> None:
    async with JungApiClient(ClientSettings("http://localhost:8000")) as client:
        session_id = uuid4()
        client_message_id = uuid4()
        intent = client.new_chat_intent(
            session_id,
            "hello",
            client_message_id=client_message_id,
        )
        command = client.new_message_command(intent, expected_revision=1)
        failure_request_id = uuid4()
        event = ErrorEvent(
            type="error",
            error=ErrorEnvelope(
                code="llm_timeout",
                message="Generation failed",
                request_id=failure_request_id,
                retryable=True,
            ),
            request_id=failure_request_id,
            session_id=None,
            client_message_id=None,
            turn_id=uuid4(),
        )
        with pytest.raises(JungProtocolError) as raised:
            client._match_decisive_event(
                event,
                intent=intent,
                command=command,
            )
        assert raised.value.kind is ProtocolErrorKind.INVALID_SERVER_EVENT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session_id", "client_message_id"),
    ((None, None), (None, "retained"), ("retained", None), ("other", "retained"), ("retained", "other")),
)
async def test_correlated_no_turn_error_requires_exact_identity(
    session_id: UUID | None | str,
    client_message_id: UUID | None | str,
) -> None:
    async with JungApiClient(ClientSettings("http://localhost:8000")) as client:
        intent = client.new_chat_intent(uuid4(), "hello")
        command = client.new_message_command(intent, expected_revision=1)
        event = ErrorEvent(
            type="error",
            error=ErrorEnvelope(
                code="state_conflict",
                message="Revision changed",
                request_id=command.request_id,
                retryable=True,
            ),
            request_id=command.request_id,
            session_id=(
                intent.session_id if session_id == "retained" else uuid4()
                if session_id == "other"
                else None
            ),
            client_message_id=(
                intent.client_message_id
                if client_message_id == "retained"
                else uuid4()
                if client_message_id == "other"
                else None
            ),
        )

        with pytest.raises(JungProtocolError) as raised:
            client._match_decisive_event(event, intent=intent, command=command)
        assert raised.value.kind is ProtocolErrorKind.INVALID_SERVER_EVENT


@pytest.mark.asyncio
@pytest.mark.parametrize("matching_identity", (True, False))
async def test_no_turn_error_with_different_request_id_is_ignored(
    matching_identity: bool,
) -> None:
    async with JungApiClient(ClientSettings("http://localhost:8000")) as client:
        intent = client.new_chat_intent(uuid4(), "hello")
        command = client.new_message_command(intent, expected_revision=1)
        request_id = uuid4()
        event = ErrorEvent(
            type="error",
            error=ErrorEnvelope(
                code="state_conflict",
                message="Revision changed",
                request_id=request_id,
                retryable=True,
            ),
            request_id=request_id,
            session_id=intent.session_id if matching_identity else uuid4(),
            client_message_id=(
                intent.client_message_id if matching_identity else uuid4()
            ),
        )

        assert client._match_decisive_event(event, intent=intent, command=command) == (
            False,
            None,
        )


@pytest.mark.asyncio
async def test_progress_events_require_internal_consistency_then_match_intent() -> None:
    async with JungApiClient(ClientSettings("http://localhost:8000")) as client:
        intent = client.new_chat_intent(uuid4(), "hello")
        command = client.new_message_command(intent, expected_revision=1)
        exact = MessageInProgressEvent(
            type="message_in_progress",
            session_id=intent.session_id,
            turn=_turn(
                session_id=intent.session_id,
                client_message_id=intent.client_message_id,
            ),
        )
        same_session_other_message = MessageInProgressEvent(
            type="message_in_progress",
            session_id=intent.session_id,
            turn=_turn(session_id=intent.session_id, client_message_id=uuid4()),
        )
        other_session_id = uuid4()
        other_session = MessageInProgressEvent(
            type="message_in_progress",
            session_id=other_session_id,
            turn=_turn(session_id=other_session_id, client_message_id=uuid4()),
        )
        inconsistent = MessageInProgressEvent(
            type="message_in_progress",
            session_id=intent.session_id,
            turn=_turn(session_id=uuid4(), client_message_id=uuid4()),
        )

        assert client._match_decisive_event(
            exact, intent=intent, command=command
        ) == (True, None)
        assert client._match_decisive_event(
            same_session_other_message,
            intent=intent,
            command=command,
        ) == (False, None)
        assert client._match_decisive_event(
            other_session, intent=intent, command=command
        ) == (False, None)
        with pytest.raises(JungProtocolError) as raised:
            client._match_decisive_event(
                inconsistent, intent=intent, command=command
            )
        assert raised.value.kind is ProtocolErrorKind.INVALID_SERVER_EVENT


@pytest.mark.asyncio
async def test_completion_events_require_internal_consistency_then_match_intent() -> None:
    async with JungApiClient(ClientSettings("http://localhost:8000")) as client:
        intent = client.new_chat_intent(uuid4(), "hello")
        command = client.new_message_command(intent, expected_revision=1)

        def completed(*, session_id: UUID, client_message_id: UUID) -> MessageCompletedEvent:
            return MessageCompletedEvent(
                type="message_completed",
                session_id=session_id,
                turn=_turn(
                    session_id=session_id,
                    client_message_id=client_message_id,
                ),
                message=_message(
                    session_id=session_id,
                    client_message_id=client_message_id,
                    role="assistant",
                    content="reply",
                    sequence=2,
                ),
            )

        exact = completed(
            session_id=intent.session_id,
            client_message_id=intent.client_message_id,
        )
        same_session_other_message = completed(
            session_id=intent.session_id,
            client_message_id=uuid4(),
        )
        other_session = completed(session_id=uuid4(), client_message_id=uuid4())
        wrong_turn_session = completed(
            session_id=intent.session_id,
            client_message_id=intent.client_message_id,
        ).model_copy(
            update={"turn": _turn(session_id=uuid4(), client_message_id=uuid4())}
        )
        wrong_message_session = completed(
            session_id=intent.session_id,
            client_message_id=intent.client_message_id,
        ).model_copy(
            update={
                "message": _message(
                    session_id=uuid4(),
                    client_message_id=intent.client_message_id,
                    role="assistant",
                    content="reply",
                    sequence=2,
                )
            }
        )
        wrong_client_message = completed(
            session_id=intent.session_id,
            client_message_id=intent.client_message_id,
        ).model_copy(
            update={
                "message": _message(
                    session_id=intent.session_id,
                    client_message_id=uuid4(),
                    role="assistant",
                    content="reply",
                    sequence=2,
                )
            }
        )

        assert client._match_decisive_event(
            exact, intent=intent, command=command
        ) == (True, None)
        assert client._match_decisive_event(
            same_session_other_message,
            intent=intent,
            command=command,
        ) == (False, None)
        assert client._match_decisive_event(
            other_session, intent=intent, command=command
        ) == (False, None)
        for inconsistent in (
            wrong_turn_session,
            wrong_message_session,
            wrong_client_message,
        ):
            with pytest.raises(JungProtocolError) as raised:
                client._match_decisive_event(
                    inconsistent, intent=intent, command=command
                )
            assert raised.value.kind is ProtocolErrorKind.INVALID_SERVER_EVENT


@pytest.mark.asyncio
async def test_exact_no_turn_error_matches_and_durable_other_identity_is_ignored() -> None:
    async with JungApiClient(ClientSettings("http://localhost:8000")) as client:
        intent = client.new_chat_intent(uuid4(), "hello")
        command = client.new_message_command(intent, expected_revision=1)
        command_error = ErrorEvent(
            type="error",
            error=ErrorEnvelope(
                code="state_conflict",
                message="Revision changed",
                request_id=command.request_id,
                retryable=True,
            ),
            request_id=command.request_id,
            session_id=intent.session_id,
            client_message_id=intent.client_message_id,
        )
        failure_request_id = uuid4()
        other_durable_error = ErrorEvent(
            type="error",
            error=ErrorEnvelope(
                code="llm_timeout",
                message="Generation failed",
                request_id=failure_request_id,
                retryable=True,
            ),
            request_id=failure_request_id,
            session_id=uuid4(),
            client_message_id=uuid4(),
            turn_id=uuid4(),
        )

        assert client._match_decisive_event(
            command_error, intent=intent, command=command
        ) == (True, command_error)
        assert client._match_decisive_event(
            other_durable_error, intent=intent, command=command
        ) == (False, None)


async def _reconciliation_harness(monkeypatch, client: JungApiClient, chat) -> None:
    @asynccontextmanager
    async def open_chat():
        yield chat

    monkeypatch.setattr(client, "open_chat", open_chat)


@pytest.mark.asyncio
async def test_reconciliation_cancellation_skips_final_refresh(monkeypatch) -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))
    session_id = uuid4()
    intent = client.new_chat_intent(session_id, "hello")
    initial = (
        _snapshot(),
        _history(
            session_id=session_id,
            client_message_id=intent.client_message_id,
        ),
    )
    refresh = AsyncMock(return_value=initial)
    chat = SimpleNamespace(send=AsyncMock())
    await _reconciliation_harness(monkeypatch, client, chat)
    monkeypatch.setattr(client, "_refresh_chat_state", refresh)
    monkeypatch.setattr(
        client,
        "_wait_for_decisive_event",
        AsyncMock(side_effect=asyncio.CancelledError),
    )

    with pytest.raises(asyncio.CancelledError):
        await client.reconcile_chat_turn(intent)
    assert refresh.await_count == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_reconciliation_closure_uses_final_durable_completion(
    monkeypatch,
) -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))
    session_id = uuid4()
    intent = client.new_chat_intent(session_id, "hello")
    initial = (
        _snapshot(revision=3),
        _history(
            session_id=session_id,
            client_message_id=intent.client_message_id,
        ),
    )
    final = (
        _snapshot(revision=5),
        _history(
            session_id=session_id,
            client_message_id=intent.client_message_id,
            user_contents=("hello",),
            assistant_contents=("reply",),
        ),
    )
    refresh = AsyncMock(side_effect=[initial, final])
    chat = SimpleNamespace(
        send=AsyncMock(side_effect=JungConnectionClosed(code=1006, reason="sensitive"))
    )
    await _reconciliation_harness(monkeypatch, client, chat)
    monkeypatch.setattr(client, "_refresh_chat_state", refresh)

    result = await client.reconcile_chat_turn(intent)

    assert result.status is ChatReconciliationStatus.COMPLETE
    assert refresh.await_count == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_event_silent_retransmission_uses_final_durable_completion(
    monkeypatch,
) -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))
    session_id = uuid4()
    intent = client.new_chat_intent(session_id, "hello")
    initial = (
        _snapshot(revision=3),
        _history(
            session_id=session_id,
            client_message_id=intent.client_message_id,
        ),
    )
    final = (
        _snapshot(revision=5),
        _history(
            session_id=session_id,
            client_message_id=intent.client_message_id,
            user_contents=("hello",),
            assistant_contents=("reply",),
        ),
    )
    refresh = AsyncMock(side_effect=[initial, final])
    chat = SimpleNamespace(send=AsyncMock())
    await _reconciliation_harness(monkeypatch, client, chat)
    monkeypatch.setattr(client, "_refresh_chat_state", refresh)
    monkeypatch.setattr(
        client,
        "_wait_for_decisive_event",
        AsyncMock(return_value=None),
    )

    result = await client.reconcile_chat_turn(intent)

    assert result.status is ChatReconciliationStatus.COMPLETE
    chat.send.assert_awaited_once()
    assert refresh.await_count == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_reconciliation_closure_without_evidence_is_unresolved(
    monkeypatch,
) -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))
    session_id = uuid4()
    intent = client.new_chat_intent(session_id, "hello")
    state = (
        _snapshot(),
        _history(
            session_id=session_id,
            client_message_id=intent.client_message_id,
        ),
    )
    refresh = AsyncMock(side_effect=[state, state])
    chat = SimpleNamespace(
        send=AsyncMock(side_effect=JungConnectionClosed(code=1006, reason=None))
    )
    await _reconciliation_harness(monkeypatch, client, chat)
    monkeypatch.setattr(client, "_refresh_chat_state", refresh)

    result = await client.reconcile_chat_turn(intent)

    assert result.status is ChatReconciliationStatus.UNRESOLVED
    assert refresh.await_count == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_reconciliation_protocol_failure_refreshes_then_reraises(
    monkeypatch,
) -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))
    session_id = uuid4()
    intent = client.new_chat_intent(session_id, "hello")
    state = (
        _snapshot(),
        _history(
            session_id=session_id,
            client_message_id=intent.client_message_id,
        ),
    )
    refresh = AsyncMock(side_effect=[state, state])
    protocol_error = JungProtocolError(
        kind=ProtocolErrorKind.INVALID_SERVER_EVENT,
        expected_model="ServerEvent",
    )
    chat = SimpleNamespace(send=AsyncMock())
    await _reconciliation_harness(monkeypatch, client, chat)
    monkeypatch.setattr(client, "_refresh_chat_state", refresh)
    monkeypatch.setattr(
        client,
        "_wait_for_decisive_event",
        AsyncMock(side_effect=protocol_error),
    )

    with pytest.raises(JungProtocolError) as raised:
        await client.reconcile_chat_turn(intent)
    assert raised.value is protocol_error
    assert refresh.await_count == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_final_refresh_failure_supersedes_uncertain_connection(
    monkeypatch,
) -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))
    session_id = uuid4()
    intent = client.new_chat_intent(session_id, "hello")
    initial = (
        _snapshot(),
        _history(
            session_id=session_id,
            client_message_id=intent.client_message_id,
        ),
    )
    final_failure = JungTransportError("final refresh")
    refresh = AsyncMock(side_effect=[initial, final_failure])
    chat = SimpleNamespace(
        send=AsyncMock(side_effect=JungConnectionClosed(code=1006, reason=None))
    )
    await _reconciliation_harness(monkeypatch, client, chat)
    monkeypatch.setattr(client, "_refresh_chat_state", refresh)

    with pytest.raises(JungTransportError) as raised:
        await client.reconcile_chat_turn(intent)
    assert raised.value is final_failure
    assert refresh.await_count == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_handshake_failure_performs_no_refresh(monkeypatch) -> None:
    client = JungApiClient(ClientSettings("http://localhost:8000"))
    intent = client.new_chat_intent(uuid4(), "hello")
    refresh = AsyncMock()

    @asynccontextmanager
    async def failing_open_chat():
        raise JungTransportError("WebSocket handshake")
        yield

    monkeypatch.setattr(client, "open_chat", failing_open_chat)
    monkeypatch.setattr(client, "_refresh_chat_state", refresh)

    with pytest.raises(JungTransportError):
        await client.reconcile_chat_turn(intent)
    refresh.assert_not_awaited()
    await client.aclose()


@pytest.mark.asyncio
async def test_durable_failure_matches_without_request_id_continuity() -> None:
    async with JungApiClient(ClientSettings("http://localhost:8000")) as client:
        session_id = uuid4()
        intent = client.new_chat_intent(session_id, "hello")
        command = client.new_message_command(intent, expected_revision=1)
        failure_request_id = uuid4()
        assert failure_request_id != command.request_id
        event = ErrorEvent(
            type="error",
            error=ErrorEnvelope(
                code="llm_timeout",
                message="Generation failed",
                request_id=failure_request_id,
                retryable=True,
            ),
            request_id=failure_request_id,
            session_id=session_id,
            client_message_id=intent.client_message_id,
            turn_id=uuid4(),
        )

        decisive, matched = client._match_decisive_event(
            event,
            intent=intent,
            command=command,
        )

        assert decisive is True
        assert matched is event


def test_reconciliation_result_enforces_status_payload() -> None:
    session_id = uuid4()
    history = _history(session_id=session_id, client_message_id=uuid4())
    with pytest.raises(ValidationError):
        ChatReconciliationResult(
            status=ChatReconciliationStatus.COMPLETE,
            snapshot=_snapshot(),
            history=history,
        )
