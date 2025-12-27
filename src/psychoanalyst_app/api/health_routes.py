"""Health check routes."""

from __future__ import annotations

from quart import Blueprint


def create_health_routes(server) -> Blueprint:
    """Create blueprint for health check endpoints."""
    bp = Blueprint("health", __name__)

    @bp.route("/health", methods=["GET"])
    async def health_check():
        """Health check endpoint."""
        return await server._health_check()

    return bp
