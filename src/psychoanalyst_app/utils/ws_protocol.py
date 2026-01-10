"""Auto-generated from schemas/ws_protocol.json. Do not edit by hand."""

from typing import Final

WS_PROTOCOL_VERSION: Final[str] = "1.2.3"


class ClientMessageTypes:
    """Message types sent from client to server."""

    CHAT_MESSAGE: Final[str] = "chat_message"
    END_SESSION: Final[str] = "end_session"


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
