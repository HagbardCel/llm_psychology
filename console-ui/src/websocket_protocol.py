"""
WebSocket Protocol Constants for Console Client.

This module defines the WebSocket protocol constants to ensure consistency
with the backend implementation. All constants match the protocol specification
in docs/WEBSOCKET_PROTOCOL.md.
"""

from typing import Final

# Protocol Version
WS_PROTOCOL_VERSION: Final[str] = "1.2.3"


# Client → Server Message Types
class ClientMessageTypes:
    """Message types sent from client to server."""

    CHAT_MESSAGE: Final[str] = "chat_message"
    END_SESSION: Final[str] = "end_session"


# Server → Client Message Types
class ServerMessageTypes:
    """Message types sent from server to client."""

    CONNECTED: Final[str] = "connected"
    SESSION_STARTED: Final[str] = "session_started"
    CHAT_RESPONSE_CHUNK: Final[str] = "chat_response_chunk"
    TYPING_START: Final[str] = "typing_start"
    TYPING_STOP: Final[str] = "typing_stop"
    WORKFLOW_NEXT_ACTION: Final[str] = "workflow_next_action"
    SESSION_ENDED: Final[str] = "session_ended"
    ASSESSMENT_RECOMMENDATIONS: Final[str] = "assessment_recommendations"
    ERROR: Final[str] = "error"


# Connection States
class ConnectionStates:
    """WebSocket connection states."""

    CONNECTING: Final[str] = "connecting"
    CONNECTED: Final[str] = "connected"
    DISCONNECTED: Final[str] = "disconnected"
    RECONNECTING: Final[str] = "reconnecting"
    ERROR: Final[str] = "error"


# Error Codes
class ErrorCodes:
    """WebSocket error codes matching backend implementation."""

    INVALID_MESSAGE_FORMAT: Final[str] = "invalid_message_format"
    MISSING_REQUIRED_FIELD: Final[str] = "missing_required_field"
    SESSION_NOT_FOUND: Final[str] = "session_not_found"
    INTERNAL_ERROR: Final[str] = "internal_error"
    RATE_LIMIT_EXCEEDED: Final[str] = "rate_limit_exceeded"


# Convenience aliases for backward compatibility and easier imports
MSG_CHAT_MESSAGE = ClientMessageTypes.CHAT_MESSAGE
MSG_END_SESSION = ClientMessageTypes.END_SESSION

MSG_CONNECTED = ServerMessageTypes.CONNECTED
MSG_SESSION_STARTED = ServerMessageTypes.SESSION_STARTED
MSG_CHAT_RESPONSE_CHUNK = ServerMessageTypes.CHAT_RESPONSE_CHUNK
MSG_TYPING_START = ServerMessageTypes.TYPING_START
MSG_TYPING_STOP = ServerMessageTypes.TYPING_STOP
MSG_SESSION_ENDED = ServerMessageTypes.SESSION_ENDED
MSG_ASSESSMENT_RECOMMENDATIONS = ServerMessageTypes.ASSESSMENT_RECOMMENDATIONS
MSG_ERROR = ServerMessageTypes.ERROR
