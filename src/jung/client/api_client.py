"""Async typed client for the local Jung HTTP API."""

from __future__ import annotations

import math
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Any, Self, TypeVar
from uuid import UUID, uuid4

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    TypeAdapter,
    ValidationError,
)

from jung.api.contracts import (
    AppSnapshotResponse,
    ChatRequest,
    ErrorCode,
    ErrorEnvelope,
    ErrorEvent,
    ErrorResponse,
    HealthResponse,
    MessageCompletedEvent,
    MessageFailedEvent,
    ProfileResponse,
    ProfileUpdateRequest,
    SelectStyleRequest,
    ServerEvent,
    SessionHistoryResponse,
    SessionListResponse,
    SessionSummaryResponse,
    StartSessionResponse,
    StyleOptionsResponse,
    TokenEvent,
)

_SAFE_LOCATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ModelT = TypeVar("_ModelT", bound=BaseModel)
_NDJSON_MEDIA_TYPE = "application/x-ndjson"

_ALLOWED_HTTP_ERROR_STATUSES: dict[ErrorCode, frozenset[int]] = {
    "invalid_command": frozenset({409}),
    "busy": frozenset({409}),
    "not_found": frozenset({404}),
    "validation_error": frozenset({422}),
    "internal_error": frozenset({500}),
    "not_ready": frozenset({503}),
}


def _validated_origin(value: str) -> httpx.URL:
    if not isinstance(value, str) or "?" in value or "#" in value:
        raise ValueError("base_url must be a valid HTTP(S) origin")
    try:
        url = httpx.URL(value)
    except Exception:
        raise ValueError("base_url must be a valid HTTP(S) origin") from None

    if (
        url.scheme not in {"http", "https"}
        or url.host is None
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise ValueError("base_url must be a valid HTTP(S) origin")
    return url.copy_with(path="/")


def _validated_timeout(value: float, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite and strictly positive")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{name} must be finite and strictly positive")
    return normalized


def _normalized_media_type(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    return content_type.split(";", 1)[0].strip().lower()


@dataclass(frozen=True, slots=True)
class ClientSettings:
    base_url: str
    transport_timeout: float = 10.0

    def __post_init__(self) -> None:
        _validated_origin(self.base_url)
        _validated_timeout(self.transport_timeout, name="transport_timeout")


class ProtocolErrorKind(StrEnum):
    INVALID_RESPONSE_BODY = "invalid_response_body"
    INVALID_ERROR_BODY = "invalid_error_body"
    MISSING_REQUEST_ID = "missing_request_id"
    MALFORMED_REQUEST_ID = "malformed_request_id"
    REQUEST_ID_MISMATCH = "request_id_mismatch"
    UNEXPECTED_STATUS = "unexpected_status"
    ERROR_STATUS_CODE_MISMATCH = "error_status_code_mismatch"
    INVALID_STREAM_RESPONSE = "invalid_stream_response"
    INVALID_STREAM_EVENT = "invalid_stream_event"
    INVALID_SERVER_EVENT = "invalid_server_event"
    INCOMPLETE_STREAM = "incomplete_stream"
    IMPOSSIBLE_HISTORY = "impossible_history"


class ProtocolValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    location: tuple[str | int, ...]
    validation_type: str
    expected_model: str


class JungClientError(Exception):
    """Base class for operational client failures."""


class JungApiError(JungClientError):
    def __init__(self, *, status: int, error: ErrorResponse) -> None:
        self.status = status
        self.code = error.code
        self.message = error.message
        self.request_id = error.request_id
        self.retryable = error.retryable
        super().__init__(self._safe_summary())

    def _safe_summary(self) -> str:
        return (
            f"Jung API error status={self.status} code={self.code} "
            f"request_id={self.request_id} retryable={self.retryable}"
        )

    def __str__(self) -> str:
        return self._safe_summary()

    def __repr__(self) -> str:
        return f"JungApiError({self._safe_summary()!r})"


class JungProtocolError(JungClientError):
    def __init__(
        self,
        *,
        kind: ProtocolErrorKind,
        route: str | None = None,
        status: int | None = None,
        expected_model: str | None = None,
        issues: tuple[ProtocolValidationIssue, ...] = (),
    ) -> None:
        self.kind = kind
        self.route = route
        self.status = status
        self.expected_model = expected_model
        self.issues = issues
        super().__init__(self._safe_summary())

    def _safe_summary(self) -> str:
        parts = [f"Jung protocol error kind={self.kind.value}"]
        if self.route is not None:
            parts.append(f"route={self.route}")
        if self.status is not None:
            parts.append(f"status={self.status}")
        if self.expected_model is not None:
            parts.append(f"expected={self.expected_model}")
        return " ".join(parts)

    def __str__(self) -> str:
        return self._safe_summary()

    def __repr__(self) -> str:
        return f"JungProtocolError({self._safe_summary()!r})"


class JungTransportError(JungClientError):
    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"Jung transport error during {operation}")


def _safe_location(location: tuple[Any, ...]) -> tuple[str | int, ...]:
    safe: list[str | int] = []
    for item in location:
        if isinstance(item, int):
            safe.append(item)
        elif isinstance(item, str) and _SAFE_LOCATION.fullmatch(item):
            safe.append(item)
        else:
            safe.append("<field>")
    return tuple(safe)


def _sanitize_validation_issues(
    exc: ValidationError,
    *,
    expected_model: str,
) -> tuple[ProtocolValidationIssue, ...]:
    issues: list[ProtocolValidationIssue] = []
    for error in exc.errors(include_url=False, include_input=False)[:20]:
        issues.append(
            ProtocolValidationIssue(
                location=_safe_location(tuple(error.get("loc", ()))),
                validation_type=str(error.get("type", "validation_error")),
                expected_model=expected_model,
            )
        )
    return tuple(issues)


def _nested_error_envelopes(value: object) -> Iterator[ErrorEnvelope]:
    if isinstance(value, ErrorEnvelope):
        yield value
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            yield from _nested_error_envelopes(getattr(value, field_name))
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _nested_error_envelopes(item)


ServerEventAdapter = TypeAdapter(ServerEvent)


class JungApiClient:
    def __init__(
        self,
        settings: ClientSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._base_url = _validated_origin(settings.base_url)
        self._transport_timeout = _validated_timeout(
            settings.transport_timeout,
            name="transport_timeout",
        )
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._transport_timeout,
            transport=transport,
        )
        self._closed = False

    async def __aenter__(self) -> Self:
        self._ensure_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        await self.aclose()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("JungApiClient is closed")

    async def aclose(self) -> None:
        if self._closed:
            return
        await self._http.aclose()
        self._closed = True

    def _url(self, route: str) -> httpx.URL:
        return self._base_url.join(route.removeprefix("/"))

    def _stream_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self._transport_timeout,
            read=None,
            write=self._transport_timeout,
            pool=self._transport_timeout,
        )

    def _response_request_id(
        self,
        response: httpx.Response,
        *,
        sent_request_id: UUID,
        route: str,
    ) -> UUID:
        value = response.headers.get("X-Request-ID")
        if value is None:
            raise JungProtocolError(
                kind=ProtocolErrorKind.MISSING_REQUEST_ID,
                route=route,
                status=response.status_code,
            )
        try:
            returned = UUID(value)
        except (TypeError, ValueError, AttributeError):
            raise JungProtocolError(
                kind=ProtocolErrorKind.MALFORMED_REQUEST_ID,
                route=route,
                status=response.status_code,
            ) from None
        if returned != sent_request_id:
            raise JungProtocolError(
                kind=ProtocolErrorKind.REQUEST_ID_MISMATCH,
                route=route,
                status=response.status_code,
            )
        return returned

    def _decode_model(
        self,
        content: bytes,
        model: type[_ModelT],
        *,
        kind: ProtocolErrorKind,
        route: str,
        status: int,
    ) -> _ModelT:
        try:
            return model.model_validate_json(content)
        except ValidationError as exc:
            issues = _sanitize_validation_issues(
                exc,
                expected_model=model.__name__,
            )
            raise JungProtocolError(
                kind=kind,
                route=route,
                status=status,
                expected_model=model.__name__,
                issues=issues,
            ) from None

    def _validate_nested_request_ids(
        self,
        model: BaseModel,
        *,
        request_id: UUID,
        route: str,
        status: int,
    ) -> None:
        if isinstance(model, ErrorResponse) and model.request_id != request_id:
            raise JungProtocolError(
                kind=ProtocolErrorKind.REQUEST_ID_MISMATCH,
                route=route,
                status=status,
            )
        if any(
            envelope.request_id != request_id
            for envelope in _nested_error_envelopes(model)
        ):
            raise JungProtocolError(
                kind=ProtocolErrorKind.REQUEST_ID_MISMATCH,
                route=route,
                status=status,
            )

    def _raise_http_error_response(
        self,
        *,
        content: bytes,
        status_code: int,
        returned_request_id: UUID,
        route: str,
    ) -> None:
        error_kind = (
            ProtocolErrorKind.UNEXPECTED_STATUS
            if 200 <= status_code < 300
            else ProtocolErrorKind.INVALID_ERROR_BODY
        )
        error = self._decode_model(
            content,
            ErrorResponse,
            kind=error_kind,
            route=route,
            status=status_code,
        )
        self._validate_nested_request_ids(
            error,
            request_id=returned_request_id,
            route=route,
            status=status_code,
        )
        allowed_statuses = _ALLOWED_HTTP_ERROR_STATUSES.get(error.code)
        if allowed_statuses is None or status_code not in allowed_statuses:
            raise JungProtocolError(
                kind=ProtocolErrorKind.ERROR_STATUS_CODE_MISMATCH,
                route=route,
                status=status_code,
                expected_model=f"error code {error.code!r}",
            )
        raise JungApiError(status=status_code, error=error)

    def _validate_event_matches_request(
        self,
        *,
        session_id: UUID,
        client_message_id: UUID,
        request_id: UUID,
        event: ServerEvent,
    ) -> None:
        if event.request_id != request_id:
            raise JungProtocolError(
                kind=ProtocolErrorKind.REQUEST_ID_MISMATCH,
                expected_model=type(event).__name__,
            )
        if (
            event.session_id != session_id
            or event.client_message_id != client_message_id
        ):
            raise JungProtocolError(
                kind=ProtocolErrorKind.INVALID_SERVER_EVENT,
                expected_model=type(event).__name__,
            )

    async def _request(
        self,
        method: str,
        route: str,
        *,
        expected_status: int,
        response_model: type[_ModelT],
        body: BaseModel | None = None,
    ) -> _ModelT:
        self._ensure_open()
        request_id = uuid4()
        try:
            response = await self._http.request(
                method,
                self._url(route),
                headers={"X-Request-ID": str(request_id)},
                json=body.model_dump(mode="json") if body is not None else None,
            )
        except httpx.HTTPError:
            raise JungTransportError(f"HTTP {method} {route}") from None

        returned_request_id = self._response_request_id(
            response,
            sent_request_id=request_id,
            route=route,
        )
        if response.status_code == expected_status:
            decoded = self._decode_model(
                response.content,
                response_model,
                kind=ProtocolErrorKind.INVALID_RESPONSE_BODY,
                route=route,
                status=response.status_code,
            )
            self._validate_nested_request_ids(
                decoded,
                request_id=returned_request_id,
                route=route,
                status=response.status_code,
            )
            return decoded

        self._raise_http_error_response(
            content=response.content,
            status_code=response.status_code,
            returned_request_id=returned_request_id,
            route=route,
        )

    async def get_state(self) -> AppSnapshotResponse:
        return await self._request(
            "GET",
            "/api/v1/state",
            expected_status=200,
            response_model=AppSnapshotResponse,
        )

    async def get_profile(self) -> ProfileResponse:
        return await self._request(
            "GET",
            "/api/v1/profile",
            expected_status=200,
            response_model=ProfileResponse,
        )

    async def update_profile(
        self,
        request: ProfileUpdateRequest,
    ) -> AppSnapshotResponse:
        return await self._request(
            "PUT",
            "/api/v1/profile",
            expected_status=200,
            response_model=AppSnapshotResponse,
            body=request,
        )

    async def get_styles(self) -> StyleOptionsResponse:
        return await self._request(
            "GET",
            "/api/v1/styles",
            expected_status=200,
            response_model=StyleOptionsResponse,
        )

    async def select_style(
        self,
        request: SelectStyleRequest,
    ) -> AppSnapshotResponse:
        return await self._request(
            "PUT",
            "/api/v1/style",
            expected_status=200,
            response_model=AppSnapshotResponse,
            body=request,
        )

    async def list_sessions(self) -> tuple[SessionSummaryResponse, ...]:
        response = await self._request(
            "GET",
            "/api/v1/sessions",
            expected_status=200,
            response_model=SessionListResponse,
        )
        return tuple(response.sessions)

    async def get_session(self, session_id: UUID) -> SessionHistoryResponse:
        return await self._request(
            "GET",
            f"/api/v1/sessions/{session_id}",
            expected_status=200,
            response_model=SessionHistoryResponse,
        )

    async def start_session(self) -> StartSessionResponse:
        return await self._request(
            "POST",
            "/api/v1/sessions",
            expected_status=201,
            response_model=StartSessionResponse,
        )

    async def end_session(self, session_id: UUID) -> AppSnapshotResponse:
        return await self._request(
            "POST",
            f"/api/v1/sessions/{session_id}/end",
            expected_status=202,
            response_model=AppSnapshotResponse,
        )

    async def retry_current_operation(self) -> AppSnapshotResponse:
        return await self._request(
            "POST",
            "/api/v1/operations/current/retry",
            expected_status=202,
            response_model=AppSnapshotResponse,
        )

    async def get_health(self) -> HealthResponse:
        return await self._request(
            "GET",
            "/api/v1/health",
            expected_status=200,
            response_model=HealthResponse,
        )

    @asynccontextmanager
    async def stream_message(
        self,
        session_id: UUID,
        content: str,
        *,
        client_message_id: UUID,
        request_id: UUID,
    ) -> AsyncIterator[AsyncIterator[ServerEvent]]:
        self._ensure_open()
        route = "/api/v1/chat"
        body = ChatRequest(
            session_id=session_id,
            client_message_id=client_message_id,
            content=content,
        )

        try:
            async with self._http.stream(
                "POST",
                self._url(route),
                headers={
                    "X-Request-ID": str(request_id),
                    "Accept": _NDJSON_MEDIA_TYPE,
                },
                json=body.model_dump(mode="json"),
                timeout=self._stream_timeout(),
            ) as response:
                returned_request_id = self._response_request_id(
                    response,
                    sent_request_id=request_id,
                    route=route,
                )
                if response.status_code == 200:
                    if (
                        _normalized_media_type(response.headers.get("content-type"))
                        != _NDJSON_MEDIA_TYPE
                    ):
                        raise JungProtocolError(
                            kind=ProtocolErrorKind.INVALID_STREAM_RESPONSE,
                            route=route,
                            status=response.status_code,
                            expected_model=_NDJSON_MEDIA_TYPE,
                        )

                    async def events() -> AsyncIterator[ServerEvent]:
                        try:
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                try:
                                    event = ServerEventAdapter.validate_json(line)
                                except ValidationError as exc:
                                    issues = _sanitize_validation_issues(
                                        exc,
                                        expected_model="ServerEvent",
                                    )
                                    raise JungProtocolError(
                                        kind=ProtocolErrorKind.INVALID_STREAM_EVENT,
                                        route=route,
                                        expected_model="ServerEvent",
                                        issues=issues,
                                    ) from None

                                self._validate_event_matches_request(
                                    session_id=session_id,
                                    client_message_id=client_message_id,
                                    request_id=returned_request_id,
                                    event=event,
                                )

                                if isinstance(
                                    event,
                                    (
                                        MessageCompletedEvent,
                                        MessageFailedEvent,
                                        ErrorEvent,
                                    ),
                                ):
                                    yield event
                                    return
                                if isinstance(event, TokenEvent):
                                    yield event
                                    continue
                                raise JungProtocolError(
                                    kind=ProtocolErrorKind.INVALID_SERVER_EVENT,
                                    route=route,
                                    expected_model="ServerEvent",
                                )
                        except httpx.HTTPError:
                            raise JungTransportError(
                                f"HTTP POST {route} stream"
                            ) from None

                        raise JungProtocolError(
                            kind=ProtocolErrorKind.INCOMPLETE_STREAM,
                            route=route,
                            expected_model="terminal ServerEvent",
                        )

                    yield events()
                    return

                if 200 <= response.status_code < 300:
                    raise JungProtocolError(
                        kind=ProtocolErrorKind.UNEXPECTED_STATUS,
                        route=route,
                        status=response.status_code,
                    )

                content_bytes = await response.aread()
                self._raise_http_error_response(
                    content=content_bytes,
                    status_code=response.status_code,
                    returned_request_id=returned_request_id,
                    route=route,
                )
        except httpx.HTTPError:
            raise JungTransportError(f"HTTP POST {route}") from None
