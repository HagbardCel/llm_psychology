"""Request helpers for consistent API validation."""

from __future__ import annotations

from typing import Any

from quart import jsonify, request


def require_user_id(data: dict[str, Any] | None = None):
    """
    Resolve a user_id from either query params or request body.

    Returns:
        tuple[str | None, tuple[Response, int] | None]: (user_id, error_response)
    """
    user_id = None
    if data is not None:
        user_id = data.get("user_id")

    if not user_id:
        user_id = request.args.get("user_id")

    if not user_id:
        return None, (jsonify({"error": "User ID is required"}), 400)

    return user_id, None


def require_session_id(data: dict[str, Any] | None = None):
    """
    Resolve a session_id from either query params or request body.

    Returns:
        tuple[str | None, tuple[Response, int] | None]: (session_id, error_response)
    """
    session_id = None
    if data is not None:
        session_id = data.get("session_id")

    if not session_id:
        session_id = request.args.get("session_id")

    if not session_id:
        return None, (jsonify({"error": "Session ID is required"}), 400)

    return session_id, None


async def validate_session_for_user(server, user_id: str, session_id: str):
    """Ensure the session exists, belongs to the user, and is active."""
    if not server.orchestrator.is_session_active(user_id, session_id):
        return jsonify({"error": "Session is not active for user"}), 400

    session = await server.db_service.get_session(session_id)
    if not session or session.user_id != user_id:
        return jsonify({"error": "Session does not belong to user"}), 400

    return None
