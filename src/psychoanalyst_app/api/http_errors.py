"""HTTP error helpers for API routes."""

from __future__ import annotations

from quart import jsonify
from pydantic import ValidationError


def validation_error_response(error: ValidationError):
    """Convert a ValidationError into a consistent HTTP response payload."""
    parts = []
    for err in error.errors():
        location = ".".join(
            str(loc) for loc in err.get("loc", []) if loc is not None
        )
        prefix = f"{location}: " if location else ""
        parts.append(f"{prefix}{err.get('msg', 'Invalid value')}")
    message = "; ".join(parts) if parts else "Invalid request payload"
    return jsonify({"error": f"Invalid request: {message}"}), 400

