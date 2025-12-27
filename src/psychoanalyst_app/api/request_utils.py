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
