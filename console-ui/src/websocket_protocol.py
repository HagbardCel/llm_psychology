"""
WebSocket Protocol Constants for Console Client.

AUTO-GENERATED from schemas/ws_protocol.json. Do not edit by hand.
"""

from typing import Final

# Protocol Version
WS_PROTOCOL_VERSION: Final[str] = "1.2.3"


# Client -> Server Message Types
class ClientMessageTypes:
    """Message types sent from client to server."""

    CHAT_MESSAGE: Final[str] = "chat_message"
    END_SESSION: Final[str] = "end_session"


# Server -> Client Message Types
class ServerMessageTypes:
    """Message types sent from server to client."""

    CONNECTED: Final[str] = "connected"
    SESSION_STARTED: Final[str] = "session_started"
    WORKFLOW_NEXT_ACTION: Final[str] = "workflow_next_action"
    CHAT_RESPONSE_CHUNK: Final[str] = "chat_response_chunk"
    TYPING_START: Final[str] = "typing_start"
    TYPING_STOP: Final[str] = "typing_stop"
    ASSESSMENT_RECOMMENDATIONS: Final[str] = "assessment_recommendations"
    SESSION_ENDED: Final[str] = "session_ended"
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
    CHAT_DISABLED_INITIAL_GREETING: Final[str] = "chat_disabled_initial_greeting"
    CHAT_DISABLED_WORKFLOW_WAIT: Final[str] = "chat_disabled_workflow_wait"
    INTERNAL_ERROR: Final[str] = "internal_error"
    RATE_LIMIT_EXCEEDED: Final[str] = "rate_limit_exceeded"
