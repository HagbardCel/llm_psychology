"""WebSocket stream/message dispatch helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from psychoanalyst_app.utils.ws_messages import (
    chat_chunk_message,
    error_message,
    typing_message,
    ws_message,
)

logger = logging.getLogger(__name__)


async def send_stream_chunk(
    *,
    websockets: dict[str, Any],
    session_id: str,
    chunk: str,
    is_complete: bool = False,
) -> None:
    """Send a streaming chunk payload to session websocket if available."""
    ws = websockets.get(session_id)
    if ws:
        try:
            await ws.send(json.dumps(chat_chunk_message(chunk, is_complete=is_complete)))
        except Exception as exc:
            logger.error("Error sending chunk to session %s: %s", session_id, exc)
        return

    logger.warning(
        "No WebSocket registered for session %s when trying to send chunk. "
        "Registered sessions: %s",
        session_id,
        list(websockets.keys()),
    )


async def send_typing_indicator(
    *,
    websockets: dict[str, Any],
    session_id: str,
    is_typing: bool,
) -> None:
    """Send typing indicator payload to websocket when available."""
    ws = websockets.get(session_id)
    if ws:
        try:
            await ws.send(json.dumps(typing_message(is_typing)))
        except Exception as exc:
            logger.error(
                "Error sending typing indicator to session %s: %s",
                session_id,
                exc,
            )
        return

    logger.debug(
        "Skipping typing indicator for session %s (no websocket registered). "
        "Registered sessions: %s",
        session_id,
        list(websockets.keys()),
    )


async def send_json_message(
    *,
    websockets: dict[str, Any],
    session_id: str,
    message_type: str,
    data: dict[str, Any],
) -> None:
    """Send an arbitrary websocket JSON envelope."""
    ws = websockets.get(session_id)
    if not ws:
        logger.warning(
            "No WebSocket registered for session %s when sending %s (active sessions: %s)",
            session_id,
            message_type,
            list(websockets.keys()),
        )
        return

    try:
        await ws.send(json.dumps(ws_message(message_type, data)))
    except Exception:
        logger.error(
            "Failed to send %s message for session %s",
            message_type,
            session_id,
            exc_info=True,
        )


async def run_background_streamer(
    *,
    session_id: str,
    websockets: dict[str, Any],
    get_context,
    stream_response,
) -> None:
    """Run background response stream with websocket typing/chunk events."""
    ws = websockets.get(session_id)
    if not ws:
        logger.error(
            "No websocket registered for session %s. Cannot stream background response.",
            session_id,
        )
        return

    context = await get_context(session_id)
    is_streaming = False
    try:
        async for chunk in stream_response(context=context):
            if not is_streaming:
                is_streaming = True
                await ws.send(json.dumps(typing_message(True)))

            await ws.send(json.dumps(chat_chunk_message(chunk, is_complete=False)))

        await ws.send(json.dumps(chat_chunk_message("", is_complete=True)))

    except Exception as exc:
        logger.error(
            "Error in background streamer for session %s: %s",
            session_id,
            exc,
            exc_info=True,
        )
        await ws.send(
            json.dumps(
                error_message(
                    "An error occurred while generating the initial response. Please try again."
                )
            )
        )
    finally:
        if is_streaming:
            await ws.send(json.dumps(typing_message(False)))
