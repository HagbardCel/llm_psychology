"""
Helpers for building WebSocket protocol envelopes.
"""

from __future__ import annotations

from typing import Any

from psychoanalyst_app.utils.ws_protocol import ServerMessageTypes


def ws_message(message_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": message_type}
    if data is not None:
        payload["data"] = data
    return payload


def chat_chunk_message(chunk: str, *, is_complete: bool) -> dict[str, Any]:
    return ws_message(
        ServerMessageTypes.CHAT_RESPONSE_CHUNK,
        {"chunk": chunk, "is_complete": is_complete},
    )


def typing_message(is_typing: bool) -> dict[str, Any]:
    return ws_message(
        ServerMessageTypes.TYPING_START if is_typing else ServerMessageTypes.TYPING_STOP
    )


def connected_message(user_id: str, name: str, status: str) -> dict[str, Any]:
    return ws_message(
        ServerMessageTypes.CONNECTED,
        {"user_id": user_id, "name": name, "status": status},
    )


def session_started_message(session_info: Any) -> dict[str, Any]:
    if hasattr(session_info, "to_dict"):
        data = session_info.to_dict()
    else:
        data = session_info
    return ws_message(ServerMessageTypes.SESSION_STARTED, data)


def workflow_next_action_message(payload: dict[str, Any]) -> dict[str, Any]:
    """Encapsulate the workflow_next_action event payload."""
    return ws_message(ServerMessageTypes.WORKFLOW_NEXT_ACTION, payload)


def error_message(message: str) -> dict[str, Any]:
    return ws_message(ServerMessageTypes.ERROR, {"message": message})
