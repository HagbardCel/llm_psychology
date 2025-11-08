"""
Message handler for WebSocket communication.

Routes incoming WebSocket events to the appropriate gateway handlers.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MessageHandler:
    """Routes WebSocket messages to gateway handlers."""

    def __init__(self, connection_manager, websocket_gateway):
        """
        Initialize the message handler.

        Args:
            connection_manager: Connection manager instance
            websocket_gateway: WebSocket gateway instance
        """
        self.connection_manager = connection_manager
        self.gateway = websocket_gateway

        # Map events to gateway methods
        self.message_handlers = {
            "chat_message": self.gateway.handle_chat_message,
            "session_request": self.gateway.handle_session_request,
            "user_status_request": self.gateway.handle_user_status_request,
            "style_selection": self.gateway.handle_style_selection,
            "session_extension": self.gateway.handle_session_extension,
            "typing_start": self._handle_typing_start,
            "typing_stop": self._handle_typing_stop,
            "ping": self._handle_ping,
        }

    async def handle_message(
        self, sid: str, event: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Handle incoming WebSocket message.

        Args:
            sid: Socket ID
            event: Event type
            data: Message data

        Returns:
            Optional response data
        """
        try:
            # Verify authentication
            if not self.connection_manager.is_authenticated(sid):
                logger.warning(f"Unauthenticated message from {sid}: {event}")
                return {"error": "Not authenticated"}

            # Update activity timestamp
            self.connection_manager.update_activity(sid)

            # Route to appropriate handler
            if event in self.message_handlers:
                handler = self.message_handlers[event]
                await handler(sid, data)
                return None  # Handlers emit directly via Socket.IO
            else:
                logger.warning(f"Unknown event type: {event}")
                return {"error": f"Unknown event type: {event}"}

        except Exception as e:
            logger.error(f"Error handling message from {sid}: {e}", exc_info=True)
            return {"error": "Message processing failed"}

    # Simple handlers that don't need gateway delegation

    async def _handle_typing_start(self, sid: str, data: Dict[str, Any]) -> None:
        """Handle typing start indicator."""
        user_id = self.connection_manager.get_user_id(sid)
        logger.debug(f"User {user_id} started typing")

    async def _handle_typing_stop(self, sid: str, data: Dict[str, Any]) -> None:
        """Handle typing stop indicator."""
        user_id = self.connection_manager.get_user_id(sid)
        logger.debug(f"User {user_id} stopped typing")

    async def _handle_ping(self, sid: str, data: Dict[str, Any]) -> None:
        """Handle ping for connection testing."""
        await self.gateway.sio.emit(
            "pong", {"timestamp": datetime.now().isoformat()}, room=sid
        )
