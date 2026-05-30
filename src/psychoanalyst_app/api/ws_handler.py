"""WebSocket handler registration."""

from __future__ import annotations

import json
import logging

from quart import websocket

from psychoanalyst_app.orchestration.orchestrator_helpers import (
    session_type_for_workflow_state,
)
from psychoanalyst_app.models.api_models import RequiredWorkflowAction
from psychoanalyst_app.utils.ws_protocol import ClientMessageTypes, ServerMessageTypes
from psychoanalyst_app.utils.ws_messages import (
    chat_chunk_message,
    connected_message,
    error_message,
    session_started_message,
)

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
            await websocket.send(
                json.dumps(
                    error_message(
                        "User profile not found. Register before opening a session."
                    )
                )
            )
            await websocket.close(1008, "profile_not_found")
            logger.warning("WebSocket rejected unknown user: %s", user_id)
            return

        await websocket.send(
            json.dumps(
                connected_message(
                    user_id,
                    user_profile.name,
                    user_profile.status.value,
                )
            )
        )

        workflow_state = await server.orchestrator.get_user_state(user_id)
        session_type = session_type_for_workflow_state(workflow_state)
        session_info = await server.orchestrator.ensure_session_for_user(
            user_id,
            session_type=session_type,
            send_initial_message=False,
        )
        session_id = session_info.session_id
        server.conversation_manager.register_websocket(session_id, websocket)
        await websocket.send(json.dumps(session_started_message(session_info)))
        await server.orchestrator.emit_workflow_next_action(
            user_id,
            session_id,
            emission_source="websocket_connect_emit",
            include_resume_payloads=True,
            force_emit=True,
        )
        await server.orchestrator.ensure_assessment_job(user_id, session_id)

        logger.info("WebSocket connection established for user: %s", user_id)

        try:
            while True:
                raw_message = await websocket.receive()
                message = json.loads(raw_message)
                msg_type = message.get("type")

                if msg_type == ClientMessageTypes.CHAT_MESSAGE:
                    if not session_id:
                        await websocket.close(1002, "No active session")
                        return

                    if server.conversation_manager.is_initial_greeting_pending(
                        session_id
                    ):
                        await server.conversation_manager.send_json_message(
                            session_id,
                            ServerMessageTypes.ERROR,
                            {
                                "code": "chat_disabled_initial_greeting",
                                "message": (
                                    "Chat is disabled until the initial greeting "
                                    "finishes."
                                ),
                            },
                        )
                        continue

                    action = await server.orchestrator.get_workflow_next_action(
                        user_id, session_id=session_id
                    )
                    if action.required_action == RequiredWorkflowAction.WAIT:
                        await server.conversation_manager.send_json_message(
                            session_id,
                            ServerMessageTypes.ERROR,
                            {
                                "code": "chat_disabled_workflow_wait",
                                "message": (
                                    "Chat is disabled while the workflow is waiting."
                                )
                            },
                        )
                        continue

                    await _handle_chat_message_ws(
                        websocket=websocket,
                        orchestrator=server.orchestrator,
                        raw_message=raw_message,
                        session_id=session_id,
                        user_id=user_id,
                    )
                elif msg_type == ClientMessageTypes.END_SESSION:
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
        if message.get("type") != ClientMessageTypes.CHAT_MESSAGE:
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
            "Error handling chat message in session %s: %s",
            session_id,
            exc,
            exc_info=True,
        )
