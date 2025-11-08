"""
WebSocket Gateway for streaming therapy sessions.

This gateway connects WebSocket clients to the orchestration layer,
enabling real-time streaming of LLM responses.
"""

import logging
from typing import Optional

import socketio

from orchestration.agent_orchestrator import AgentOrchestrator
from orchestration.models import WorkflowState
from websocket_server.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class WebSocketGateway:
    """
    Gateway for WebSocket client communication.

    Handles WebSocket events and streams agent responses to clients.
    """

    def __init__(
        self,
        sio: socketio.AsyncServer,
        orchestrator: AgentOrchestrator,
        connection_manager: ConnectionManager,
    ):
        """
        Initialize the WebSocket gateway.

        Args:
            sio: Socket.IO server instance
            orchestrator: Agent orchestrator
            connection_manager: Connection manager
        """
        self.sio = sio
        self.orchestrator = orchestrator
        self.connection_manager = connection_manager

    async def handle_chat_message(self, sid: str, data: dict) -> None:
        """
        Handle incoming chat message from client.

        Args:
            sid: Socket ID
            data: Message data containing 'message' and optional 'session_id'
        """
        try:
            user_id = self.connection_manager.get_user_id(sid)
            if not user_id:
                await self.sio.emit(
                    "error", {"message": "Not authenticated"}, room=sid
                )
                return

            message = data.get("message", "").strip()
            if not message:
                await self.sio.emit(
                    "error", {"message": "Empty message"}, room=sid
                )
                return

            session_id = data.get("session_id")

            logger.info(f"Processing message from user {user_id}: {message[:50]}...")

            # Emit typing indicator
            await self.sio.emit("typing_start", room=sid)

            try:
                # Stream response from orchestrator
                full_response = ""
                async for chunk in self.orchestrator.process_message(
                    user_id, message, session_id
                ):
                    full_response += chunk
                    await self.sio.emit(
                        "chat_response_chunk",
                        {"chunk": chunk, "is_complete": False},
                        room=sid,
                    )

                # Signal completion
                await self.sio.emit("typing_stop", room=sid)
                await self.sio.emit(
                    "chat_response_chunk",
                    {
                        "chunk": "",
                        "is_complete": True,
                        "full_response": full_response,
                    },
                    room=sid,
                )

                logger.info(
                    f"Completed streaming response to {user_id} "
                    f"({len(full_response)} chars)"
                )

            except Exception as e:
                logger.error(f"Error streaming response: {e}", exc_info=True)
                await self.sio.emit("typing_stop", room=sid)
                await self.sio.emit(
                    "error",
                    {"message": "Failed to generate response"},
                    room=sid,
                )

        except Exception as e:
            logger.error(f"Error handling chat message: {e}", exc_info=True)
            await self.sio.emit(
                "error", {"message": "Internal server error"}, room=sid
            )

    async def handle_session_request(self, sid: str, data: dict) -> None:
        """
        Handle session start request.

        Args:
            sid: Socket ID
            data: Session data containing 'type' (optional)
        """
        try:
            user_id = self.connection_manager.get_user_id(sid)
            if not user_id:
                await self.sio.emit(
                    "error", {"message": "Not authenticated"}, room=sid
                )
                return

            # Get current workflow state
            state = await self.orchestrator.get_user_state(user_id)

            # Determine session type from state
            session_type = self.orchestrator.workflow_engine.get_current_agent(state)

            logger.info(
                f"Starting session for user {user_id}, "
                f"type: {session_type}, state: {state}"
            )

            # Start session
            session_info = await self.orchestrator.start_session(
                user_id, session_type
            )

            # Emit session started event
            await self.sio.emit(
                "session_started",
                {
                    "session_id": session_info.session_id,
                    "agent_type": session_info.agent_type,
                    "workflow_state": session_info.workflow_state.value,
                    "created_at": session_info.created_at.isoformat(),
                },
                room=sid,
            )

            logger.info(
                f"Session {session_info.session_id} started for user {user_id}"
            )

        except Exception as e:
            logger.error(f"Error starting session: {e}", exc_info=True)
            await self.sio.emit(
                "error", {"message": "Failed to start session"}, room=sid
            )

    async def handle_user_status_request(self, sid: str) -> None:
        """
        Handle user status request.

        Args:
            sid: Socket ID
        """
        try:
            user_id = self.connection_manager.get_user_id(sid)
            if not user_id:
                await self.sio.emit(
                    "error", {"message": "Not authenticated"}, room=sid
                )
                return

            # Get workflow state
            state = await self.orchestrator.get_user_state(user_id)

            # Determine next agent
            next_agent = self.orchestrator.workflow_engine.get_current_agent(state)

            await self.sio.emit(
                "user_status",
                {
                    "user_id": user_id,
                    "workflow_state": state.value,
                    "next_agent": next_agent,
                },
                room=sid,
            )

            logger.debug(f"Sent status to user {user_id}: {state.value}")

        except Exception as e:
            logger.error(f"Error getting user status: {e}", exc_info=True)
            await self.sio.emit(
                "error", {"message": "Failed to get user status"}, room=sid
            )

    async def handle_style_selection(self, sid: str, data: dict) -> None:
        """
        Handle therapy style selection (for assessment phase).

        Args:
            sid: Socket ID
            data: Selection data containing 'selected_style'
        """
        try:
            user_id = self.connection_manager.get_user_id(sid)
            if not user_id:
                await self.sio.emit(
                    "error", {"message": "Not authenticated"}, room=sid
                )
                return

            selected_style = data.get("selected_style")
            if not selected_style:
                await self.sio.emit(
                    "error", {"message": "No style selected"}, room=sid
                )
                return

            logger.info(f"User {user_id} selected style: {selected_style}")

            # Get assessment agent
            assessment_agent = self.orchestrator.service_container.get_assessment_agent()

            # Get intake session (TODO: retrieve from database)
            # For now, we'll need to pass this through the orchestrator

            # Process selection
            # This will create the therapy plan and transition state

            await self.sio.emit(
                "style_selected",
                {
                    "selected_style": selected_style,
                    "message": f"Great! You've selected {selected_style.upper()} therapy.",
                },
                room=sid,
            )

            logger.info(f"Style selection processed for user {user_id}")

        except Exception as e:
            logger.error(f"Error processing style selection: {e}", exc_info=True)
            await self.sio.emit(
                "error", {"message": "Failed to process selection"}, room=sid
            )

    async def handle_session_extension(self, sid: str, data: dict) -> None:
        """
        Handle session time extension request.

        Args:
            sid: Socket ID
            data: Extension data
        """
        try:
            user_id = self.connection_manager.get_user_id(sid)
            if not user_id:
                await self.sio.emit(
                    "error", {"message": "Not authenticated"}, room=sid
                )
                return

            session_id = data.get("session_id")
            if not session_id:
                await self.sio.emit(
                    "error", {"message": "No session ID provided"}, room=sid
                )
                return

            # TODO: Implement session extension logic
            # This should update the conversation context's duration

            await self.sio.emit(
                "session_extended",
                {
                    "session_id": session_id,
                    "additional_minutes": 5,
                    "message": "Session extended by 5 minutes.",
                },
                room=sid,
            )

            logger.info(f"Extended session {session_id} for user {user_id}")

        except Exception as e:
            logger.error(f"Error extending session: {e}", exc_info=True)
            await self.sio.emit(
                "error", {"message": "Failed to extend session"}, room=sid
            )
