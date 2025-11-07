"""Message handler for WebSocket communication."""

import logging
from typing import Dict, Any, Optional
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageHandler:
    """Handles WebSocket message processing and routing."""
    
    def __init__(self, connection_manager):
        self.connection_manager = connection_manager
        self.message_handlers = {
            "chat_message": self._handle_chat_message,
            "typing_start": self._handle_typing_start,
            "typing_stop": self._handle_typing_stop,
            "ping": self._handle_ping,
            "session_request": self._handle_session_request,
        }
    
    async def handle_message(self, sid: str, event: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Handle incoming WebSocket message.
        
        Args:
            sid: Socket ID
            event: Event type
            data: Message data
            
        Returns:
            Optional[Dict[str, Any]]: Response data if any
        """
        try:
            # Verify user is authenticated
            if not self.connection_manager.is_authenticated(sid):
                logger.warning(f"Unauthenticated message from {sid}")
                return {"error": "Not authenticated"}
            
            # Update activity
            self.connection_manager.update_activity(sid)
            
            # Get user ID
            user_id = self.connection_manager.get_user_id(sid)
            if not user_id:
                return {"error": "User not found"}
            
            # Route to appropriate handler
            if event in self.message_handlers:
                handler = self.message_handlers[event]
                return await handler(sid, user_id, data)
            else:
                logger.warning(f"Unknown event type: {event}")
                return {"error": f"Unknown event type: {event}"}
                
        except Exception as e:
            logger.error(f"Error handling message from {sid}: {e}")
            return {"error": "Message processing failed"}
    
    async def _handle_chat_message(self, sid: str, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle chat message from user."""
        try:
            message = data.get("message", "").strip()
            if not message:
                return {"error": "Empty message"}
            
            # TODO: Integrate with psychoanalyst agent
            # For now, just echo the message
            response_message = f"Therapist: I understand you said '{message}'. Let's explore that further."
            
            logger.info(f"Chat message from user {user_id}: {message}")
            
            return {
                "type": "chat_response",
                "message": response_message,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error handling chat message: {e}")
            return {"error": "Failed to process chat message"}
    
    async def _handle_typing_start(self, sid: str, user_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle typing start indicator."""
        logger.debug(f"User {user_id} started typing")
        # In a multi-user scenario, we would broadcast this to other participants
        return None
    
    async def _handle_typing_stop(self, sid: str, user_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle typing stop indicator."""
        logger.debug(f"User {user_id} stopped typing")
        return None
    
    async def _handle_ping(self, sid: str, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle ping message for connection testing."""
        return {
            "type": "pong",
            "timestamp": datetime.now().isoformat()
        }
    
    async def _handle_session_request(self, sid: str, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle therapy session request."""
        try:
            session_type = data.get("session_type", "therapy")
            
            # TODO: Integrate with therapy session logic
            logger.info(f"Session request from user {user_id}: {session_type}")
            
            return {
                "type": "session_started",
                "session_type": session_type,
                "message": "Your therapy session has begun. How are you feeling today?",
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error handling session request: {e}")
            return {"error": "Failed to start session"}
    
    def validate_message_data(self, data: Dict[str, Any], required_fields: list) -> bool:
        """Validate that message data contains required fields."""
        return all(field in data for field in required_fields)
    
    def sanitize_message(self, message: str) -> str:
        """Sanitize user message content."""
        # Basic sanitization - remove any potentially harmful content
        if not isinstance(message, str):
            return ""
        
        # Limit message length
        max_length = 1000
        if len(message) > max_length:
            message = message[:max_length]
        
        return message.strip()
