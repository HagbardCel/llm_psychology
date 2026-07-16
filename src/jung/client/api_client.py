"""Async typed client for the local Jung HTTP and WebSocket API."""

from __future__ import annotations

import asyncio
import json
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
    model_validator,
)
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from jung.api.contracts import (
    AppSnapshotResponse,
    ChatTurnSummaryResponse,
    EndSessionRequest,
    ErrorEnvelope,
    ErrorEvent,
    ErrorResponse,
    HealthResponse,
    MessageResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    RetryOperationRequest,
    SelectStyleRequest,
    SendMessageCommand,
    ServerEvent,
    SessionHistoryResponse,
    SessionListResponse,
    SessionSummaryResponse,
    StartSessionRequest,
    StartSessionResponse,
    StyleOptionsResponse,
)
from jung.client._chat_events import (
    ChatEventIdentity,
    ChatEventViolation,
    matches_decisive_event,
)

_SAFE_LOCATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ModelT = TypeVar("_ModelT", bound=BaseModel)


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


@dataclass(frozen=True, slots=True)
class ClientSettings:
    base_url: str
    transport_timeout: float = 10.0
    acknowledgement_timeout: float = 5.0

    def __post_init__(self) -> None:
        _validated_origin(self.base_url)
        _validated_timeout(self.transport_timeout, name="transport_timeout")
        _validated_timeout(
            self.acknowledgement_timeout,
            name="acknowledgement_timeout",
        )


class ChatSendIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    client_message_id: UUID
    content: str


class ChatReconciliationStatus(StrEnum):
    COMPLETE = "complete"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"
    IDENTITY_CONFLICT = "identity_conflict"
    UNRESOLVED = "unresolved"


class ChatReconciliationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ChatReconciliationStatus
    snapshot: AppSnapshotResponse
    history: SessionHistoryResponse
    completed_message: MessageResponse | None = None
    pending_turn: ChatTurnSummaryResponse | None = None
    error_event: ErrorEvent | None = None
    conflicting_user_message: MessageResponse | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> Self:
        values = {
            ChatReconciliationStatus.COMPLETE: self.completed_message,
            ChatReconciliationStatus.IN_PROGRESS: self.pending_turn,
            ChatReconciliationStatus.FAILED: self.error_event,
            ChatReconciliationStatus.IDENTITY_CONFLICT: (self.conflicting_user_message),
        }
        expected = values.get(self.status)
        populated = sum(value is not None for value in values.values())
        if self.status is ChatReconciliationStatus.UNRESOLVED:
            if populated:
                raise ValueError("unresolved result cannot carry a status payload")
        elif expected is None or populated != 1:
            raise ValueError("reconciliation result payload does not match status")
        return self


class ProtocolErrorKind(StrEnum):
    INVALID_RESPONSE_BODY = "invalid_response_body"
    INVALID_ERROR_BODY = "invalid_error_body"
    MISSING_REQUEST_ID = "missing_request_id"
    MALFORMED_REQUEST_ID = "malformed_request_id"
    REQUEST_ID_MISMATCH = "request_id_mismatch"
    UNEXPECTED_STATUS = "unexpected_status"
    INVALID_WEBSOCKET_FRAME = "invalid_websocket_frame"
    INVALID_SERVER_EVENT = "invalid_server_event"
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
        self.current_snapshot = error.current_snapshot
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


class JungConnectionClosed(JungTransportError):
    def __init__(self, *, code: int | None, reason: str | None) -> None:
        self.code = code
        self.reason = reason
        super().__init__("WebSocket communication")

    def __str__(self) -> str:
        return f"Jung WebSocket connection closed code={self.code}"

    def __repr__(self) -> str:
        return f"JungConnectionClosed(code={self.code!r})"


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


class JungChatConnection:
    def __init__(self, websocket: ClientConnection) -> None:
        self._websocket = websocket
        self._unusable = False
        self._close_attempted = False
        self._consumer_active = False

    def _ensure_open(self) -> None:
        if self._unusable:
            raise RuntimeError("chat connection is unusable")

    async def send(self, command: SendMessageCommand) -> None:
        self._ensure_open()
        try:
            await self._websocket.send(command.model_dump_json())
        except ConnectionClosed as exc:
            self._unusable = True
            raise JungConnectionClosed(code=exc.code, reason=exc.reason) from None
        except (OSError, WebSocketException):
            self._unusable = True
            raise JungTransportError("WebSocket send") from None

    async def events(self) -> AsyncIterator[ServerEvent]:
        self._ensure_open()
        if self._consumer_active:
            raise RuntimeError("chat events already have an active consumer")
        self._consumer_active = True
        try:
            while True:
                try:
                    raw = await self._websocket.recv()
                except ConnectionClosed as exc:
                    self._unusable = True
                    raise JungConnectionClosed(
                        code=exc.code,
                        reason=exc.reason,
                    ) from None
                except (OSError, WebSocketException):
                    self._unusable = True
                    raise JungTransportError("WebSocket receive") from None

                if not isinstance(raw, str):
                    raise JungProtocolError(
                        kind=ProtocolErrorKind.INVALID_WEBSOCKET_FRAME,
                        expected_model="JSON text frame",
                    )
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, TypeError, ValueError):
                    raise JungProtocolError(
                        kind=ProtocolErrorKind.INVALID_WEBSOCKET_FRAME,
                        expected_model="ServerEvent",
                    ) from None
                try:
                    event = ServerEventAdapter.validate_python(payload)
                except ValidationError as exc:
                    issues = _sanitize_validation_issues(
                        exc,
                        expected_model="ServerEvent",
                    )
                    raise JungProtocolError(
                        kind=ProtocolErrorKind.INVALID_SERVER_EVENT,
                        expected_model="ServerEvent",
                        issues=issues,
                    ) from None
                yield event
        finally:
            self._consumer_active = False

    async def aclose(self) -> None:
        if self._close_attempted:
            return
        self._close_attempted = True
        self._unusable = True
        try:
            await self._websocket.close()
        except asyncio.CancelledError:
            self._close_attempted = False
            raise
        except (OSError, WebSocketException):
            return


ServerEventAdapter = TypeAdapter(ServerEvent)


class JungApiClient:
    def __init__(self, settings: ClientSettings) -> None:
        self.settings = settings
        self._base_url = _validated_origin(settings.base_url)
        self._transport_timeout = _validated_timeout(
            settings.transport_timeout,
            name="transport_timeout",
        )
        self._acknowledgement_timeout = _validated_timeout(
            settings.acknowledgement_timeout,
            name="acknowledgement_timeout",
        )
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._transport_timeout,
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

    def _websocket_url(self) -> str:
        scheme = "wss" if self._base_url.scheme == "https" else "ws"
        return str(self._base_url.copy_with(scheme=scheme).join("api/v1/chat"))

    def new_chat_intent(
        self,
        session_id: UUID,
        content: str,
        *,
        client_message_id: UUID | None = None,
    ) -> ChatSendIntent:
        return ChatSendIntent(
            session_id=session_id,
            client_message_id=client_message_id or uuid4(),
            content=content,
        )

    def new_message_command(
        self,
        intent: ChatSendIntent,
        *,
        expected_revision: int,
        request_id: UUID | None = None,
    ) -> SendMessageCommand:
        return SendMessageCommand(
            type="send_message",
            session_id=intent.session_id,
            client_message_id=intent.client_message_id,
            request_id=request_id or uuid4(),
            expected_revision=expected_revision,
            content=intent.content,
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
        response: httpx.Response,
        model: type[_ModelT],
        *,
        kind: ProtocolErrorKind,
        route: str,
    ) -> _ModelT:
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            issues = _sanitize_validation_issues(
                exc,
                expected_model=model.__name__,
            )
            raise JungProtocolError(
                kind=kind,
                route=route,
                status=response.status_code,
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
                response,
                response_model,
                kind=ProtocolErrorKind.INVALID_RESPONSE_BODY,
                route=route,
            )
            self._validate_nested_request_ids(
                decoded,
                request_id=returned_request_id,
                route=route,
                status=response.status_code,
            )
            return decoded

        error_kind = (
            ProtocolErrorKind.UNEXPECTED_STATUS
            if 200 <= response.status_code < 300
            else ProtocolErrorKind.INVALID_ERROR_BODY
        )
        error = self._decode_model(
            response,
            ErrorResponse,
            kind=error_kind,
            route=route,
        )
        self._validate_nested_request_ids(
            error,
            request_id=returned_request_id,
            route=route,
            status=response.status_code,
        )
        raise JungApiError(status=response.status_code, error=error)

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

    async def start_session(
        self,
        request: StartSessionRequest,
    ) -> StartSessionResponse:
        return await self._request(
            "POST",
            "/api/v1/sessions",
            expected_status=201,
            response_model=StartSessionResponse,
            body=request,
        )

    async def end_session(
        self,
        session_id: UUID,
        request: EndSessionRequest,
    ) -> AppSnapshotResponse:
        return await self._request(
            "POST",
            f"/api/v1/sessions/{session_id}/end",
            expected_status=202,
            response_model=AppSnapshotResponse,
            body=request,
        )

    async def retry_current_operation(
        self,
        request: RetryOperationRequest,
    ) -> AppSnapshotResponse:
        return await self._request(
            "POST",
            "/api/v1/operations/current/retry",
            expected_status=202,
            response_model=AppSnapshotResponse,
            body=request,
        )

    async def get_health(self) -> HealthResponse:
        return await self._request(
            "GET",
            "/api/v1/health",
            expected_status=200,
            response_model=HealthResponse,
        )

    @asynccontextmanager
    async def open_chat(self) -> AsyncIterator[JungChatConnection]:
        self._ensure_open()
        try:
            websocket = await connect(
                self._websocket_url(),
                open_timeout=self._transport_timeout,
                close_timeout=self._transport_timeout,
            )
        except asyncio.CancelledError:
            raise
        except (TimeoutError, OSError, WebSocketException):
            raise JungTransportError("WebSocket handshake") from None

        chat = JungChatConnection(websocket)
        try:
            yield chat
        finally:
            await chat.aclose()

    async def _refresh_chat_state(
        self,
        session_id: UUID,
    ) -> tuple[AppSnapshotResponse, SessionHistoryResponse]:
        snapshot = await self.get_state()
        history = await self.get_session(session_id)
        return snapshot, history

    def _classify_chat_state(
        self,
        intent: ChatSendIntent,
        snapshot: AppSnapshotResponse,
        history: SessionHistoryResponse,
        *,
        matched_error: ErrorEvent | None = None,
    ) -> ChatReconciliationResult | None:
        if history.session.id != intent.session_id:
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="SessionHistoryResponse",
            )

        users = [
            message
            for message in history.messages
            if message.client_message_id == intent.client_message_id
            and message.role == "user"
        ]
        assistants = [
            message
            for message in history.messages
            if message.client_message_id == intent.client_message_id
            and message.role == "assistant"
        ]
        if len(users) > 1 or len(assistants) > 1 or (assistants and not users):
            raise JungProtocolError(
                kind=ProtocolErrorKind.IMPOSSIBLE_HISTORY,
                expected_model="SessionHistoryResponse",
            )

        if users and users[0].content != intent.content:
            return ChatReconciliationResult(
                status=ChatReconciliationStatus.IDENTITY_CONFLICT,
                snapshot=snapshot,
                history=history,
                conflicting_user_message=users[0],
            )
        if users and assistants:
            return ChatReconciliationResult(
                status=ChatReconciliationStatus.COMPLETE,
                snapshot=snapshot,
                history=history,
                completed_message=assistants[0],
            )

        pending = snapshot.active_chat_turn
        if (
            users
            and pending is not None
            and pending.session_id == intent.session_id
            and pending.client_message_id == intent.client_message_id
        ):
            return ChatReconciliationResult(
                status=ChatReconciliationStatus.IN_PROGRESS,
                snapshot=snapshot,
                history=history,
                pending_turn=pending,
            )
        if matched_error is not None:
            return ChatReconciliationResult(
                status=ChatReconciliationStatus.FAILED,
                snapshot=snapshot,
                history=history,
                error_event=matched_error,
            )
        return None

    def _match_decisive_event(
        self,
        event: ServerEvent,
        *,
        intent: ChatSendIntent,
        command: SendMessageCommand,
    ) -> tuple[bool, ErrorEvent | None]:
        try:
            return matches_decisive_event(
                event,
                identity=ChatEventIdentity(
                    session_id=intent.session_id,
                    client_message_id=intent.client_message_id,
                    request_id=command.request_id,
                ),
            )
        except ChatEventViolation as exc:
            raise JungProtocolError(
                kind=ProtocolErrorKind.INVALID_SERVER_EVENT,
                expected_model=exc.expected_model,
            ) from None

    async def _wait_for_decisive_event(
        self,
        chat: JungChatConnection,
        *,
        intent: ChatSendIntent,
        command: SendMessageCommand,
        acknowledgement_timeout: float,
    ) -> ErrorEvent | None:
        try:
            async with asyncio.timeout(acknowledgement_timeout):
                async for event in chat.events():
                    decisive, error = self._match_decisive_event(
                        event,
                        intent=intent,
                        command=command,
                    )
                    if decisive:
                        return error
        except TimeoutError:
            return None
        return None

    async def reconcile_chat_turn(
        self,
        intent: ChatSendIntent,
        *,
        acknowledgement_timeout: float | None = None,
    ) -> ChatReconciliationResult:
        self._ensure_open()
        timeout = (
            self._acknowledgement_timeout
            if acknowledgement_timeout is None
            else _validated_timeout(
                acknowledgement_timeout,
                name="acknowledgement_timeout",
            )
        )

        async with self.open_chat() as chat:
            snapshot, history = await self._refresh_chat_state(intent.session_id)
            initial = self._classify_chat_state(intent, snapshot, history)
            if initial is not None:
                return initial

            command = self.new_message_command(
                intent,
                expected_revision=snapshot.revision,
            )
            matched_error: ErrorEvent | None = None
            protocol_failure: JungProtocolError | None = None
            try:
                await chat.send(command)
                matched_error = await self._wait_for_decisive_event(
                    chat,
                    intent=intent,
                    command=command,
                    acknowledgement_timeout=timeout,
                )
            except asyncio.CancelledError:
                raise
            except JungProtocolError as exc:
                protocol_failure = exc
            except (JungConnectionClosed, JungTransportError):
                pass

            final_snapshot, final_history = await self._refresh_chat_state(
                intent.session_id
            )
            if protocol_failure is not None:
                raise protocol_failure
            final = self._classify_chat_state(
                intent,
                final_snapshot,
                final_history,
                matched_error=matched_error,
            )
            if final is not None:
                return final
            return ChatReconciliationResult(
                status=ChatReconciliationStatus.UNRESOLVED,
                snapshot=final_snapshot,
                history=final_history,
            )
