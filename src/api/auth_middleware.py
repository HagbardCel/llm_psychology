"""Authentication middleware for protecting routes with JWT verification."""

import logging
from functools import wraps

from quart import jsonify, request

from services.auth_service import AuthService

logger = logging.getLogger(__name__)


def create_auth_middleware(auth_service: AuthService, require_authentication: bool):
    """
    Create authentication middleware decorator.

    Args:
        auth_service: AuthService instance for token verification
        require_authentication: Whether to enforce authentication

    Returns:
        Decorator function for protecting routes
    """

    def require_auth(f):
        """
        Decorator to require authentication for a route.

        Extracts JWT token from Authorization header, verifies it,
        and attaches user_id to request context.

        Usage:
            @app.route('/protected')
            @require_auth
            async def protected_route():
                user_id = request.user_id
                return jsonify({'user_id': user_id})
        """

        @wraps(f)
        async def decorated_function(*args, **kwargs):
            # If authentication is disabled (dev mode), skip verification
            if not require_authentication:
                logger.debug("Authentication disabled, skipping verification")
                return await f(*args, **kwargs)

            # Get Authorization header
            auth_header = request.headers.get("Authorization")

            if not auth_header:
                logger.warning(f"Missing Authorization header for {request.path}")
                return jsonify({"error": "Missing authorization header"}), 401

            # Check Bearer scheme
            parts = auth_header.split()
            if len(parts) != 2 or parts[0].lower() != "bearer":
                logger.warning(
                    f"Invalid Authorization header format for {request.path}: {auth_header}"
                )
                return (
                    jsonify(
                        {
                            "error": "Invalid authorization header format. Use: Bearer <token>"
                        }
                    ),
                    401,
                )

            token = parts[1]

            # Verify token
            payload = auth_service.verify_token(token)
            if not payload:
                logger.warning(f"Invalid or expired token for {request.path}")
                return jsonify({"error": "Invalid or expired token"}), 401

            # Attach user_id to request context
            request.user_id = payload.user_id
            request.username = payload.username

            logger.debug(f"Authenticated user: {payload.username} for {request.path}")

            return await f(*args, **kwargs)

        return decorated_function

    return require_auth


def require_auth_websocket(auth_service: AuthService, require_authentication: bool):
    """
    Authentication check for WebSocket connections.

    For WebSocket, token is passed as query parameter: /ws?token=<jwt_token>

    Args:
        auth_service: AuthService instance
        require_authentication: Whether to enforce authentication

    Returns:
        tuple: (user_id, username) if authenticated, (None, None) otherwise
    """

    async def verify_websocket_auth():
        """Verify WebSocket authentication from query parameter."""
        # If authentication is disabled, skip verification
        if not require_authentication:
            logger.debug("Authentication disabled for WebSocket")
            return ("anonymous", "anonymous")

        # Get token from query parameter
        from quart import websocket

        token = websocket.args.get("token")

        if not token:
            logger.warning("Missing token in WebSocket connection")
            return (None, None)

        # Verify token
        payload = auth_service.verify_token(token)
        if not payload:
            logger.warning("Invalid or expired WebSocket token")
            return (None, None)

        logger.info(f"WebSocket authenticated: {payload.username}")
        return (payload.user_id, payload.username)

    return verify_websocket_auth
