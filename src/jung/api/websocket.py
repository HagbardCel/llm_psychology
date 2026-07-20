"""WebSocket adapter for /api/v1/chat."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import assert_never
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from jung.api.contracts import (
    ErrorCode,
    ErrorEnvelope,
    MappingContext,
    SendMessageCommand,
    ServerEvent,
    build_error_event,
    map_application_event,
    to_snapshot_response,
)
from jung.api.deps import ApiNotReady, WebSocketRuntime, get_websocket_runtime
from jung.api.errors import new_request_id, to_error_envelope
from jung.api.settings import ApiSettings
from jung.domain.commands import SendMessage
from jung.domain.errors import DomainError, RevisionConflict, StoredWorkFailure
from jung.events import (
    ApplicationEvent,
    ChatTokenGenerated,
    ChatTurnAccepted,
    ChatTurnCompleted,
    ChatTurnFailed,
    OperationChanged,
    SnapshotChanged,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

_VALIDATION_MESSAGE = "Request validation failed."


class _SlowClient(Exception):
    pass


def recover_request_id(payload: object) -> UUID | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("request_id")
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def mapping_context_for_event(
    event: ApplicationEvent,
    *,
    turn_request_ids: dict[UUID, UUID],
    connection_id: str,
) -> MappingContext:
    match event:
        case ChatTurnAccepted():
            request_id = event.request_id
            if request_id is None:
                request_id = new_request_id()
                logger.warning(
                    "ChatTurnAccepted missing request_id",
                    extra={
                        "connection_id": connection_id,
                        "session_id": str(event.session_id),
                        "turn_id": str(event.turn_id),
                        "event_type": "ChatTurnAccepted",
                    },
                )
            turn_request_ids[event.turn_id] = request_id
            return MappingContext(request_id=request_id)

        case ChatTokenGenerated():
            request_id = event.request_id
            if request_id is None:
                request_id = turn_request_ids.get(event.turn_id)
                if request_id is None:
                    request_id = new_request_id()
                logger.warning(
                    "ChatTokenGenerated missing request_id",
                    extra={
                        "connection_id": connection_id,
                        "session_id": str(event.session_id),
                        "turn_id": str(event.turn_id),
                        "event_type": "ChatTokenGenerated",
                    },
                )
            return MappingContext(request_id=request_id)

        case ChatTurnCompleted():
            request_id = turn_request_ids.pop(event.turn_id, None)
            if request_id is None:
                request_id = new_request_id()
            return MappingContext(request_id=request_id)

        case ChatTurnFailed():
            turn_request_ids.pop(event.turn_id, None)
            return MappingContext(request_id=new_request_id())

        case SnapshotChanged() | OperationChanged():
            return MappingContext(request_id=new_request_id())

        case _ as unreachable:
            assert_never(unreachable)


def _validation_envelope(request_id: UUID) -> ErrorEnvelope:
    return ErrorEnvelope(
        code="validation_error",
        message=_VALIDATION_MESSAGE,
        request_id=request_id,
        retryable=False,
        current_snapshot=None,
    )


def _log_command_rejected(
    *,
    connection_id: str,
    command: SendMessageCommand,
    error_code: ErrorCode,
    exception_type: str | None = None,
) -> None:
    fields: dict[str, object] = {
        "connection_id": connection_id,
        "request_id": str(command.request_id),
        "session_id": str(command.session_id),
        "client_message_id": str(command.client_message_id),
        "error_code": error_code,
    }
    if exception_type is not None:
        fields["exception_type"] = exception_type

    if error_code == "internal_error" and exception_type is not None:
        logger.error("websocket_command_rejected", extra=fields)
    else:
        logger.info("websocket_command_rejected", extra=fields)


def _origin_is_allowed(websocket: WebSocket, settings: ApiSettings) -> bool:
    origin = websocket.headers.get("origin")

    if origin is None:
        return True

    if origin == "null":
        return False

    return origin in settings.allowed_origins


@router.websocket("/chat")
async def chat_websocket(websocket: WebSocket) -> None:
    settings: ApiSettings = websocket.app.state.api_settings

    if not _origin_is_allowed(websocket, settings):
        await websocket.close(code=1008)
        return

    try:
        runtime = get_websocket_runtime(websocket.app.state.api)
    except ApiNotReady:
        await websocket.close()
        return

    await _handle_chat_connection(websocket, runtime, settings)


async def _handle_chat_connection(
    websocket: WebSocket,
    runtime: WebSocketRuntime,
    settings: ApiSettings,
) -> None:
    connection_id = str(uuid4())
    await websocket.accept()
    connected_at = time.monotonic()
    logger.info("websocket_connected", extra={"connection_id": connection_id})

    try:
        async with runtime.events.subscribe() as subscription:
            turn_request_ids: dict[UUID, UUID] = {}
            send_lock = asyncio.Lock()

            async def close_slow_connection() -> None:
                try:
                    async with asyncio.timeout(settings.websocket_close_timeout):
                        await websocket.close(code=1011)
                except (
                    TimeoutError,
                    RuntimeError,
                    WebSocketDisconnect,
                ) as exc:
                    logger.debug(
                        "WebSocket close failed",
                        extra={
                            "connection_id": connection_id,
                            "error_type": type(exc).__name__,
                        },
                    )

            async def send_event(event: ServerEvent) -> None:
                try:
                    async with asyncio.timeout(settings.websocket_send_timeout):
                        async with send_lock:
                            await websocket.send_json(event.model_dump(mode="json"))
                except TimeoutError:
                    await close_slow_connection()
                    raise _SlowClient from None

            async def send_validation_error(*, request_id: UUID) -> None:
                logger.info(
                    "websocket_protocol_rejected",
                    extra={
                        "connection_id": connection_id,
                        "request_id": str(request_id),
                        "error_code": "validation_error",
                    },
                )
                context = MappingContext(request_id=request_id)
                await send_event(
                    build_error_event(
                        _validation_envelope(request_id),
                        context=context,
                    )
                )

            async def inbound_loop() -> None:
                try:
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return

                        if message.get("bytes") is not None:
                            await send_validation_error(request_id=new_request_id())
                            continue

                        text = message.get("text")
                        if text is None:
                            await send_validation_error(request_id=new_request_id())
                            continue

                        try:
                            payload = json.loads(text)
                        except json.JSONDecodeError:
                            await send_validation_error(request_id=new_request_id())
                            continue

                        recovered_id = recover_request_id(payload)
                        request_id = recovered_id or new_request_id()

                        try:
                            command = SendMessageCommand.model_validate(payload)
                        except ValidationError:
                            await send_validation_error(request_id=request_id)
                            continue

                        domain_command = SendMessage(
                            expected_revision=command.expected_revision,
                            session_id=command.session_id,
                            client_message_id=command.client_message_id,
                            content=command.content,
                            request_id=command.request_id,
                        )
                        try:
                            turn = await runtime.application.submit_message(
                                domain_command
                            )
                        except RevisionConflict as exc:
                            context = MappingContext(request_id=command.request_id)
                            wire_snapshot = None
                            try:
                                snapshot = await runtime.application.get_snapshot()
                                wire_snapshot = to_snapshot_response(
                                    snapshot,
                                    context=context,
                                )
                            except Exception as enrichment_exc:
                                logger.error(
                                    "Failed to enrich WebSocket revision conflict",
                                    extra={
                                        "connection_id": connection_id,
                                        "request_id": str(command.request_id),
                                        "exception_type": type(enrichment_exc).__name__,
                                    },
                                )
                            envelope = to_error_envelope(
                                exc,
                                request_id=context.request_id,
                                current_snapshot=wire_snapshot,
                            )
                            _log_command_rejected(
                                connection_id=connection_id,
                                command=command,
                                error_code=envelope.code,
                            )
                            await send_event(
                                build_error_event(
                                    envelope,
                                    context=context,
                                    session_id=command.session_id,
                                    client_message_id=command.client_message_id,
                                )
                            )
                        except DomainError as exc:
                            context = MappingContext(request_id=command.request_id)
                            envelope = to_error_envelope(
                                exc,
                                request_id=context.request_id,
                            )
                            exception_type = (
                                type(exc).__name__
                                if envelope.code == "internal_error"
                                and not isinstance(exc, StoredWorkFailure)
                                else None
                            )
                            _log_command_rejected(
                                connection_id=connection_id,
                                command=command,
                                error_code=envelope.code,
                                exception_type=exception_type,
                            )
                            await send_event(
                                build_error_event(
                                    envelope,
                                    context=context,
                                    session_id=command.session_id,
                                    client_message_id=command.client_message_id,
                                )
                            )
                        except Exception as exc:
                            context = MappingContext(request_id=command.request_id)
                            envelope = to_error_envelope(
                                exc,
                                request_id=context.request_id,
                            )
                            _log_command_rejected(
                                connection_id=connection_id,
                                command=command,
                                error_code=envelope.code,
                                exception_type=type(exc).__name__,
                            )
                            await send_event(
                                build_error_event(
                                    envelope,
                                    context=context,
                                    session_id=command.session_id,
                                    client_message_id=command.client_message_id,
                                )
                            )
                        else:
                            logger.info(
                                "chat_command_resolved",
                                extra={
                                    "connection_id": connection_id,
                                    "request_id": str(command.request_id),
                                    "session_id": str(command.session_id),
                                    "client_message_id": str(command.client_message_id),
                                    "turn_id": str(turn.id),
                                    "turn_status": turn.status.value,
                                },
                            )
                except _SlowClient:
                    return
                except WebSocketDisconnect:
                    return

            async def outbound_loop() -> None:
                try:
                    async for event in subscription:
                        context = mapping_context_for_event(
                            event,
                            turn_request_ids=turn_request_ids,
                            connection_id=connection_id,
                        )
                        wire = map_application_event(event, context=context)
                        await send_event(wire)
                except (_SlowClient, WebSocketDisconnect):
                    return

                await close_slow_connection()

            inbound_task = asyncio.create_task(inbound_loop(), name="ws-inbound")
            outbound_task = asyncio.create_task(outbound_loop(), name="ws-outbound")
            tasks = {inbound_task, outbound_task}

            try:
                _done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, asyncio.CancelledError):
                        continue
                    if isinstance(result, BaseException):
                        raise result
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        logger.info(
            "websocket_disconnected",
            extra={
                "connection_id": connection_id,
                "duration_ms": round((time.monotonic() - connected_at) * 1000, 1),
            },
        )
