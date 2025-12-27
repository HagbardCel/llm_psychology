"""WebSocket handler registration."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from quart import websocket

from psychoanalyst_app.models.data_models import UserProfile, UserStatus
from psychoanalyst_app.utils.ws_messages import chat_chunk_message, connected_message, session_started_message

logger = logging.getLogger(__name__)


def register_ws_handler(app, server) -> None:
    """Register the primary WebSocket endpoint."""

    @app.websocket("/ws")
    async def ws_endpoint():
        """
        WebSocket endpoint using Trio structured concurrency.
        Expects user_id as a query parameter: /ws?user_id=<user_id>
        """
        session_id = None

        user_id = websocket.args.get("user_id")

        if not user_id:
            await websocket.close(1002, "user_id query parameter is required")
            logger.warning(
                "WebSocket connection rejected: missing user_id query parameter"
            )
            return

        logger.info("WebSocket connection request for user: %s", user_id)

        user_profile = await server.db_service.get_user_profile(user_id)
        if not user_profile:
            user_profile = UserProfile(
                user_id=user_id,
                name=user_id,
                status=UserStatus.PROFILE_ONLY,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            await server.db_service.save_user_profile(user_profile)
            logger.info("Auto-created profile for new user: %s", user_id)

        await websocket.send(
            json.dumps(
                connected_message(
                    user_id,
                    user_profile.name,
                    user_profile.status.value,
                )
            )
        )

        logger.info("WebSocket connection established for user: %s", user_id)

        try:
            while True:
                raw_message = await websocket.receive()
                message = json.loads(raw_message)
                msg_type = message.get("type")

                if msg_type == "session_request":
                    session_payload = message.get("data") or {}
                    requested_type = session_payload.get("session_type")
                    if not isinstance(requested_type, str):
                        requested_type = "therapy"

                    if session_id:
                        server.conversation_manager.unregister_websocket(session_id)
                        logger.info("Switching session from %s", session_id)

                    session_info = await server.orchestrator.start_session(
                        user_id,
                        session_type=requested_type,
                        send_initial_message=True,
                    )
                    session_id = session_info.session_id
                    server.conversation_manager.register_websocket(
                        session_id, websocket
                    )

                    await websocket.send(
                        json.dumps(session_started_message(session_info))
                    )

                elif msg_type == "chat_message":
                    if not session_id:
                        await websocket.close(
                            1002, "First message must be session_request"
                        )
                        return

                    await _handle_chat_message_ws(
                        websocket=websocket,
                        orchestrator=server.orchestrator,
                        raw_message=raw_message,
                        session_id=session_id,
                        user_id=user_id,
                    )
                elif msg_type == "end_session":
                    if not session_id:
                        await websocket.close(1002, "No active session to end")
                        return

                    payload = message.get("data") or {}
                    reason = payload.get("reason")
                    await server.orchestrator.end_session(
                        user_id, session_id, reason=reason
                    )
                else:
                    continue

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "WebSocket error for session %s: %s", session_id, exc, exc_info=True
            )
        finally:
            if session_id:
                server.conversation_manager.unregister_websocket(session_id)
            logger.info("WebSocket connection closed for session %s", session_id)

    logger.info("WebSocket handler configured for Trio server")


async def _handle_chat_message_ws(
    websocket,
    orchestrator,
    raw_message: str,
    session_id: str,
    user_id: str,
):
    """Handle chat messages received over the WebSocket connection."""
    try:
        message = json.loads(raw_message)
        if message.get("type") != "chat_message":
            return

        message_content = message.get("data", {}).get("message", "").strip()
        if not message_content:
            return

        async for chunk in orchestrator.process_message(
            user_id, message_content, session_id
        ):
            await websocket.send(
                json.dumps(chat_chunk_message(chunk, is_complete=False))
            )

        await websocket.send(json.dumps(chat_chunk_message("", is_complete=True)))

    except json.JSONDecodeError:
        logger.warning("Received invalid JSON in session %s", session_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error(
            "Error handling chat message in session %s: %s", session_id, exc, exc_info=True
        )
