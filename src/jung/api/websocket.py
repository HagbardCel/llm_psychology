"""One-shot WebSocket adapter for /api/v1/chat."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from jung._async_cleanup import drain_cancelled_task
from jung.api.contracts import (
    ErrorCode,
    ErrorEnvelope,
    MappingContext,
    MessageCompletedEvent,
    MessageFailedEvent,
    SendMessageCommand,
    ServerEvent,
    TokenEvent,
    build_error_event,
    normalize_public_error_code,
    to_message_response,
)
from jung.api.deps import ApiNotReady, ApiRuntime, get_websocket_runtime
from jung.api.errors import new_request_id, to_error_envelope
from jung.api.settings import ApiSettings
from jung.diagnostics import diagnostic_context
from jung.domain.commands import SendMessage
from jung.domain.errors import DomainError
from jung.domain.results import ChatCompleted, ChatFailed, ChatStreamResult, ChatToken

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


def _validation_envelope(request_id: UUID) -> ErrorEnvelope:
    return ErrorEnvelope(
        code="validation_error",
        message=_VALIDATION_MESSAGE,
        request_id=request_id,
        retryable=False,
    )


def _log_command_rejected(
    *,
    connection_id: str,
    command: SendMessageCommand | None,
    request_id: UUID,
    error_code: ErrorCode,
    exception_type: str | None = None,
    session_id: UUID | None = None,
    client_message_id: UUID | None = None,
) -> None:
    fields: dict[str, object] = {
        "connection_id": connection_id,
        "request_id": str(request_id),
        "error_code": error_code,
    }
    if command is not None:
        fields["session_id"] = str(command.session_id)
        fields["client_message_id"] = str(command.client_message_id)
    elif session_id is not None:
        fields["session_id"] = str(session_id)
    if client_message_id is not None and command is None:
        fields["client_message_id"] = str(client_message_id)
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


def _parse_command(text: str) -> tuple[SendMessageCommand | None, UUID]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, new_request_id()

    recovered_id = recover_request_id(payload)
    request_id = recovered_id or new_request_id()
    try:
        command = SendMessageCommand.model_validate(payload)
    except ValidationError:
        return None, request_id
    return command, command.request_id


def _to_server_event(item: ChatStreamResult) -> ServerEvent:
    context = MappingContext(
        request_id=item.request_id if item.request_id is not None else new_request_id()
    )
    if isinstance(item, ChatToken):
        return TokenEvent(
            type="token",
            session_id=item.session_id,
            client_message_id=item.client_message_id,
            request_id=context.request_id,
            text=item.text,
        )
    if isinstance(item, ChatCompleted):
        return MessageCompletedEvent(
            type="message_completed",
            session_id=item.session_id,
            client_message_id=item.client_message_id,
            request_id=context.request_id,
            user_message=to_message_response(item.user_message),
            assistant_message=to_message_response(item.assistant_message),
        )
    if isinstance(item, ChatFailed):
        return MessageFailedEvent(
            type="message_failed",
            session_id=item.session_id,
            client_message_id=item.client_message_id,
            request_id=context.request_id,
            error=ErrorEnvelope(
                code=normalize_public_error_code(item.code),
                message=item.message,
                request_id=context.request_id,
                retryable=None,
            ),
        )
    raise TypeError(f"unexpected chat stream result: {type(item)!r}")


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
    runtime: ApiRuntime,
    settings: ApiSettings,
) -> None:
    connection_id = str(uuid4())
    await websocket.accept()
    connected_at = time.monotonic()
    logger.info("websocket_connected", extra={"connection_id": connection_id})

    try:
        send_lock = asyncio.Lock()

        async def close_slow_connection() -> None:
            try:
                async with asyncio.timeout(settings.websocket_close_timeout):
                    await websocket.close(code=1011)
            except (TimeoutError, RuntimeError, WebSocketDisconnect) as exc:
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

        # One-shot: receive exactly one command frame.
        try:
            message = await websocket.receive()
        except WebSocketDisconnect:
            return

        if message["type"] == "websocket.disconnect":
            return

        if message.get("bytes") is not None or message.get("text") is None:
            request_id = new_request_id()
            await send_event(
                build_error_event(
                    _validation_envelope(request_id),
                    context=MappingContext(request_id=request_id),
                )
            )
            await websocket.close()
            return

        command, request_id = _parse_command(message["text"])
        if command is None:
            await send_event(
                build_error_event(
                    _validation_envelope(request_id),
                    context=MappingContext(request_id=request_id),
                )
            )
            await websocket.close()
            return

        await _stream_one_command(
            websocket=websocket,
            runtime=runtime,
            command=command,
            connection_id=connection_id,
            send_event=send_event,
            close_slow_connection=close_slow_connection,
        )
    except (_SlowClient, WebSocketDisconnect):
        return
    finally:
        logger.info(
            "websocket_disconnected",
            extra={
                "connection_id": connection_id,
                "duration_ms": round((time.monotonic() - connected_at) * 1000, 1),
            },
        )


async def _stream_one_command(
    *,
    websocket: WebSocket,
    runtime: ApiRuntime,
    command: SendMessageCommand,
    connection_id: str,
    send_event,
    close_slow_connection,
) -> None:
    domain_command = SendMessage(
        session_id=command.session_id,
        client_message_id=command.client_message_id,
        content=command.content,
        request_id=command.request_id,
    )

    with diagnostic_context(
        request_id=str(command.request_id),
        session_id=str(command.session_id),
        client_message_id=str(command.client_message_id),
    ):
        stream = runtime.application.stream_message(domain_command)
        stream_iter = stream.__aiter__()
        receive_task: asyncio.Task[Any] | None = asyncio.create_task(
            websocket.receive(),
            name="ws-receive",
        )
        stream_task: asyncio.Task[Any] | None = asyncio.create_task(
            stream_iter.__anext__(),
            name="ws-stream",
        )

        try:
            while True:
                assert receive_task is not None and stream_task is not None
                done, _pending = await asyncio.wait(
                    {receive_task, stream_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if receive_task in done:
                    try:
                        message = receive_task.result()
                    except WebSocketDisconnect:
                        await _cancel_stream(stream_task, stream)
                        return
                    except Exception:
                        await _cancel_stream(stream_task, stream)
                        raise

                    if message["type"] == "websocket.disconnect":
                        await _cancel_stream(stream_task, stream)
                        return

                    # Unexpected data frame during an active command.
                    stream_task.cancel()
                    await drain_cancelled_task(stream_task)
                    await _aclose_stream(stream)
                    await send_event(
                        build_error_event(
                            _validation_envelope(command.request_id),
                            context=MappingContext(request_id=command.request_id),
                            session_id=command.session_id,
                            client_message_id=command.client_message_id,
                        )
                    )
                    await websocket.close()
                    return

                assert stream_task in done
                try:
                    item = stream_task.result()
                except StopAsyncIteration:
                    receive_task.cancel()
                    await drain_cancelled_task(receive_task)
                    await _aclose_stream(stream)
                    return
                except DomainError as exc:
                    receive_task.cancel()
                    await drain_cancelled_task(receive_task)
                    await _aclose_stream(stream)
                    envelope = to_error_envelope(exc, request_id=command.request_id)
                    _log_command_rejected(
                        connection_id=connection_id,
                        command=command,
                        request_id=command.request_id,
                        error_code=envelope.code,
                        exception_type=(
                            type(exc).__name__
                            if envelope.code == "internal_error"
                            else None
                        ),
                    )
                    await send_event(
                        build_error_event(
                            envelope,
                            context=MappingContext(request_id=command.request_id),
                            session_id=command.session_id,
                            client_message_id=command.client_message_id,
                        )
                    )
                    await websocket.close()
                    return
                except Exception as exc:
                    receive_task.cancel()
                    await drain_cancelled_task(receive_task)
                    await _aclose_stream(stream)
                    envelope = to_error_envelope(exc, request_id=command.request_id)
                    _log_command_rejected(
                        connection_id=connection_id,
                        command=command,
                        request_id=command.request_id,
                        error_code=envelope.code,
                        exception_type=type(exc).__name__,
                    )
                    await send_event(
                        build_error_event(
                            envelope,
                            context=MappingContext(request_id=command.request_id),
                            session_id=command.session_id,
                            client_message_id=command.client_message_id,
                        )
                    )
                    await websocket.close()
                    return

                wire = _to_server_event(item)
                await send_event(wire)
                if isinstance(item, (ChatCompleted, ChatFailed)):
                    receive_task.cancel()
                    await drain_cancelled_task(receive_task)
                    await _aclose_stream(stream)
                    await websocket.close()
                    return

                # Keep the same receive_task pending; request the next stream item.
                stream_task = asyncio.create_task(
                    stream_iter.__anext__(),
                    name="ws-stream",
                )
        except _SlowClient:
            if stream_task is not None and not stream_task.done():
                stream_task.cancel()
                await drain_cancelled_task(stream_task)
            if receive_task is not None and not receive_task.done():
                receive_task.cancel()
                await drain_cancelled_task(receive_task)
            await _aclose_stream(stream)
            return


async def _cancel_stream(
    stream_task: asyncio.Task[Any],
    stream: AsyncIterator[ChatStreamResult],
) -> None:
    stream_task.cancel()
    await drain_cancelled_task(stream_task)
    await _aclose_stream(stream)


async def _aclose_stream(stream: AsyncIterator[ChatStreamResult]) -> None:
    aclose = getattr(stream, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        logger.debug("chat stream aclose failed", exc_info=True)
