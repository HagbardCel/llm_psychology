"""Initial greeting delivery helpers for newly-created sessions."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable

from psychoanalyst_app.orchestration.trio_conversation_manager import (
    TrioConversationManager,
)

logger = logging.getLogger(__name__)

ProcessMessageFn = Callable[[str, str, str | None], AsyncIterator[str]]


async def send_initial_greeting(
    *,
    user_id: str,
    session_id: str,
    conversation_manager: TrioConversationManager,
    process_message: ProcessMessageFn,
) -> None:
    """
    Send initial greeting by processing an empty message through the active agent.

    This triggers the normal message-processing path and avoids dedicated greeting
    branches per agent type.
    """
    typing_started = False
    try:
        ws_ready = await conversation_manager.wait_for_websocket(
            session_id, timeout_seconds=5.0
        )
        if not ws_ready:
            logger.warning(
                "Skipping initial greeting for session %s: websocket never registered",
                session_id,
            )
            return

        await conversation_manager.send_typing_indicator(session_id, True)
        typing_started = True

        async for chunk in process_message(user_id, "", session_id):
            await conversation_manager.send_stream_chunk(
                session_id, chunk, is_complete=False
            )

        await conversation_manager.send_stream_chunk(session_id, "", is_complete=True)
        logger.info("Initial greeting sent for session %s", session_id)

    except Exception as exc:
        logger.error(
            "Initial greeting failed for session %s: %s",
            session_id,
            exc,
            exc_info=True,
        )
        try:
            await conversation_manager.send_stream_chunk(
                session_id,
                f"\nERROR: Initial greeting failed: {type(exc).__name__}: {exc}\n",
                is_complete=False,
            )
            await conversation_manager.send_stream_chunk(
                session_id, "", is_complete=True
            )
        except Exception:
            logger.warning(
                "Failed to send initial-greeting error chunk for session %s",
                session_id,
                exc_info=True,
            )
    finally:
        conversation_manager.mark_initial_greeting_complete(session_id)
        if typing_started:
            try:
                await conversation_manager.send_typing_indicator(session_id, False)
            except Exception:
                logger.debug(
                    "Failed to send typing_stop for session %s (likely disconnected)",
                    session_id,
                    exc_info=True,
                )
