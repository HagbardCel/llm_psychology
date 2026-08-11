from __future__ import annotations

import json
import math
import traceback
from datetime import UTC, datetime
from typing import get_args
from uuid import UUID, uuid4

import httpx
import pytest

from jung.api.contracts import (
    AppSnapshotResponse,
    ErrorCode,
    ErrorEnvelope,
    HealthResponse,
    MessageCompletedEvent,
    MessageResponse,
    OperationSummaryResponse,
    TokenEvent,
)
from jung.client.api_client import (
    _ALLOWED_HTTP_ERROR_STATUSES,
    ClientSettings,
    JungApiClient,
    JungApiError,
    JungProtocolError,
    JungTransportError,
    ProtocolErrorKind,
)

_NDJSON = "application/x-ndjson"


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


def _client_with_handler(
    handler,
    *,
    base_url: str = "http://localhost:8000",
) -> JungApiClient:
    return JungApiClient(
        ClientSettings(base_url),
        transport=httpx.MockTransport(handler),
    )


def _ndjson_headers(request: httpx.Request, **extra: str) -> dict[str, str]:
    return {
        "X-Request-ID": request.headers["X-Request-ID"],
        "Content-Type": _NDJSON,
        **extra,
    }


def _token_line(
    *,
    request_id: UUID,
    session_id: UUID,
    client_message_id: UUID,
    text: str = "hi",
) -> bytes:
    return (
        TokenEvent(
            type="token",
            text=text,
            request_id=request_id,
            session_id=session_id,
            client_message_id=client_message_id,
        ).model_dump_json()
        + "\n"
    ).encode()


def _completion_line(
    *,
    request_id: UUID,
    session_id: UUID,
    client_message_id: UUID,
    content: str = "reply",
) -> bytes:
    return (
        MessageCompletedEvent(
            type="message_completed",
            request_id=request_id,
            session_id=session_id,
            client_message_id=client_message_id,
            user_message=_message(
                session_id=session_id,
                client_message_id=client_message_id,
                role="user",
                content="hello",
                sequence=1,
            ),
            assistant_message=_message(
                session_id=session_id,
                client_message_id=client_message_id,
                role="assistant",
                content=content,
                sequence=2,
            ),
        ).model_dump_json()
        + "\n"
    ).encode()


async def _collect_stream(
    client: JungApiClient,
    *,
    session_id: UUID | None = None,
    content: str = "hello",
    client_message_id: UUID | None = None,
    request_id: UUID | None = None,
) -> list[object]:
    session_id = session_id or uuid4()
    client_message_id = client_message_id or uuid4()
    request_id = request_id or uuid4()
    async with client.stream_message(
        session_id,
        content,
        client_message_id=client_message_id,
        request_id=request_id,
    ) as events:
        return [event async for event in events]


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://localhost:8000",
        "http://user:password@localhost:8000",
        "http://localhost:8000/service",
        "http://localhost:8000?query=yes",
        "http://localhost:8000#fragment",
    ],
)
def test_client_settings_reject_non_origin_urls_without_echoing_them(
    base_url: str,
) -> None:
    with pytest.raises(ValueError) as raised:
        ClientSettings(base_url)
    assert base_url not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("base_url", (None,))
def test_client_settings_reject_non_string_origins(base_url: object) -> None:
    with pytest.raises(ValueError) as raised:
        ClientSettings(base_url)  # type: ignore[arg-type]
    assert str(raised.value) == "base_url must be a valid HTTP(S) origin"
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("value", [0, math.nan, True])
def test_client_settings_reject_invalid_timeouts(value: float) -> None:
    with pytest.raises(ValueError):
        ClientSettings("http://localhost:8000", transport_timeout=value)


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
async def test_stream_message_decodes_valid_ndjson_events() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat")
        assert request.method == "POST"
        assert request.headers["Accept"] == _NDJSON
        assert request.headers["X-Request-ID"] == str(request_id)
        body = json.loads(request.content)
        assert body == {
            "session_id": str(session_id),
            "client_message_id": str(client_message_id),
            "content": "hello",
        }
        content = _token_line(
            request_id=request_id,
            session_id=session_id,
            client_message_id=client_message_id,
            text="hi",
        ) + _completion_line(
            request_id=request_id,
            session_id=session_id,
            client_message_id=client_message_id,
            content="hi there",
        )
        return httpx.Response(200, headers=_ndjson_headers(request), content=content)

    client = _client_with_handler(handler)
    events = await _collect_stream(
        client,
        session_id=session_id,
        client_message_id=client_message_id,
        request_id=request_id,
    )
    assert len(events) == 2
    assert isinstance(events[0], TokenEvent)
    assert events[0].text == "hi"
    assert isinstance(events[1], MessageCompletedEvent)
    assert events[1].assistant_message.content == "hi there"
    await client.aclose()


@pytest.mark.asyncio
async def test_invalid_stream_json_line_is_protocol_error() -> None:
    secret = "private stream disclosure"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=_ndjson_headers(request),
            content=f'{{"type":"token","text":"{secret}"\n'.encode(),
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await _collect_stream(client)
    error = raised.value
    formatted = "".join(traceback.format_exception(error))
    assert error.kind is ProtocolErrorKind.INVALID_STREAM_EVENT
    assert secret not in str(error)
    assert secret not in repr(error)
    assert secret not in formatted
    assert error.__cause__ is None
    await client.aclose()


@pytest.mark.asyncio
async def test_invalid_server_event_payload_is_protocol_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=_ndjson_headers(request),
            content=b'{"type":"token","text":1}\n',
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await _collect_stream(client)
    assert raised.value.kind is ProtocolErrorKind.INVALID_STREAM_EVENT
    await client.aclose()


@pytest.mark.asyncio
async def test_wrong_stream_content_type_is_protocol_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "X-Request-ID": request.headers["X-Request-ID"],
                "Content-Type": "application/json",
            },
            content=b"{}\n",
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await _collect_stream(client)
    assert raised.value.kind is ProtocolErrorKind.INVALID_STREAM_RESPONSE
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "expected_kind"),
    [
        (
            lambda event, _ids: {**event, "request_id": str(uuid4())},
            ProtocolErrorKind.REQUEST_ID_MISMATCH,
        ),
        (
            lambda event, _ids: {**event, "session_id": str(uuid4())},
            ProtocolErrorKind.INVALID_SERVER_EVENT,
        ),
        (
            lambda event, _ids: {**event, "client_message_id": str(uuid4())},
            ProtocolErrorKind.INVALID_SERVER_EVENT,
        ),
    ],
)
async def test_stream_rejects_mismatched_event_ids(
    mutate,
    expected_kind: ProtocolErrorKind,
) -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    token_payload = {
        "type": "token",
        "text": "hi",
        "request_id": str(request_id),
        "session_id": str(session_id),
        "client_message_id": str(client_message_id),
    }
    payload = mutate(
        token_payload,
        (session_id, client_message_id, request_id),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=_ndjson_headers(request),
            content=(json.dumps(payload) + "\n").encode(),
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await _collect_stream(
            client,
            session_id=session_id,
            client_message_id=client_message_id,
            request_id=request_id,
        )
    assert raised.value.kind is expected_kind
    summary = str(raised.value)
    assert str(request_id) not in summary
    assert str(session_id) not in summary
    assert str(client_message_id) not in summary
    await client.aclose()


@pytest.mark.asyncio
async def test_eof_before_terminal_is_incomplete_stream() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=_ndjson_headers(request),
            content=_token_line(
                request_id=request_id,
                session_id=session_id,
                client_message_id=client_message_id,
            ),
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await _collect_stream(
            client,
            session_id=session_id,
            client_message_id=client_message_id,
            request_id=request_id,
        )
    assert raised.value.kind is ProtocolErrorKind.INCOMPLETE_STREAM
    await client.aclose()


@pytest.mark.asyncio
async def test_stream_non_200_error_response_is_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        request_id = request.headers["X-Request-ID"]
        return httpx.Response(
            422,
            headers={"X-Request-ID": request_id},
            json={
                "code": "validation_error",
                "message": "invalid chat request",
                "request_id": request_id,
                "retryable": False,
            },
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungApiError) as raised:
        await _collect_stream(client)
    assert raised.value.status == 422
    assert raised.value.code == "validation_error"
    assert "invalid chat request" not in str(raised.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_stream_unexpected_2xx_is_protocol_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            headers={"X-Request-ID": request.headers["X-Request-ID"]},
            content=b"",
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungProtocolError) as raised:
        await _collect_stream(client)
    assert raised.value.kind is ProtocolErrorKind.UNEXPECTED_STATUS
    await client.aclose()


@pytest.mark.asyncio
async def test_mid_stream_httpx_failure_is_transport_error() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()

    class FailingByteStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield _token_line(
                request_id=request_id,
                session_id=session_id,
                client_message_id=client_message_id,
            )
            raise httpx.ReadError("connection reset")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=_ndjson_headers(request),
            stream=FailingByteStream(),
        )

    client = _client_with_handler(handler)
    with pytest.raises(JungTransportError) as raised:
        await _collect_stream(
            client,
            session_id=session_id,
            client_message_id=client_message_id,
            request_id=request_id,
        )
    assert "stream" in raised.value.operation
    await client.aclose()
