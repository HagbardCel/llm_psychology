"""Authentication routes for JWT-based authentication."""

import logging
from datetime import datetime

from quart import Blueprint, jsonify, request

from config import settings
from models.auth_models import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserCredentials,
    UserInfo,
)
from models.data_models import UserProfile, UserStatus
from services.auth_service import AuthService
from services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)

# Create Blueprint for auth routes
auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def create_auth_routes(db_service: TrioDatabaseService, auth_service: AuthService):
    """
    Create and configure authentication routes.

    Args:
        db_service: Database service for user management
        auth_service: Authentication service for JWT handling
    """

    @auth_bp.route("/register", methods=["POST"])
    async def register():
        """
        Register a new user.

        Request Body:
            {
                "username": "string",
                "password": "string",
                "name": "string"
            }

        Returns:
            201: User created successfully with access token
            400: Validation error or duplicate username
            500: Server error
        """
        try:
            data = await request.get_json()

            # Validate request
            try:
                register_req = RegisterRequest(**data)
            except Exception as e:
                return jsonify({"error": f"Invalid request: {str(e)}"}), 400

            # Check if username already exists
            existing = await db_service.get_user_credentials(register_req.username)
            if existing:
                return jsonify({"error": "Username already exists"}), 400

            # Generate user ID
            user_id = AuthService.generate_user_id()

            # Hash password
            password_hash = auth_service.hash_password(register_req.password)

            # Create user credentials
            credentials = UserCredentials(
                user_id=user_id,
                username=register_req.username,
                password_hash=password_hash,
                created_at=datetime.now(),
                last_login=None,
            )

            # Create user profile
            profile = UserProfile(
                user_id=user_id,
                name=register_req.name,
                birthdate=None,
                profession=None,
                status=UserStatus.PROFILE_ONLY,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            # Save to database
            creds_success = await db_service.create_user_credentials(credentials)
            profile_success = await db_service.save_user_profile(profile)

            if not creds_success or not profile_success:
                return jsonify({"error": "Failed to create user"}), 500

            # Generate access token
            login_response = auth_service.create_login_response(
                user_id, register_req.username
            )

            # Update last login
            await db_service.update_last_login(user_id, datetime.now())

            logger.info(f"New user registered: {register_req.username}")

            return jsonify(login_response.model_dump()), 201

        except Exception as e:
            logger.error(f"Registration error: {e}", exc_info=True)
            return jsonify({"error": "Internal server error"}), 500

    @auth_bp.route("/login", methods=["POST"])
    async def login():
        """
        Authenticate user and return access token.

        Request Body:
            {
                "username": "string",
                "password": "string"
            }

        Returns:
            200: Authentication successful with access token
            401: Invalid credentials
            500: Server error
        """
        try:
            data = await request.get_json()

            # Validate request
            try:
                login_req = LoginRequest(**data)
            except Exception as e:
                return jsonify({"error": f"Invalid request: {str(e)}"}), 400

            # Get user credentials
            credentials = await db_service.get_user_credentials(login_req.username)
            if not credentials:
                return jsonify({"error": "Invalid username or password"}), 401

            # Verify password
            if not auth_service.verify_password(
                login_req.password, credentials.password_hash
            ):
                return jsonify({"error": "Invalid username or password"}), 401

            # Generate access token
            login_response = auth_service.create_login_response(
                credentials.user_id, credentials.username
            )

            # Update last login
            await db_service.update_last_login(credentials.user_id, datetime.now())

            logger.info(f"User logged in: {login_req.username}")

            return jsonify(login_response.model_dump()), 200

        except Exception as e:
            logger.error(f"Login error: {e}", exc_info=True)
            return jsonify({"error": "Internal server error"}), 500

    @auth_bp.route("/me", methods=["GET"])
    async def get_current_user():
        """
        Get current authenticated user information.

        Requires: Authorization header with Bearer token

        Returns:
            200: User information
            401: Not authenticated
            500: Server error
        """
        try:
            # Get user_id from request context (set by auth middleware)
            user_id = getattr(request, "user_id", None)
            if not user_id:
                return jsonify({"error": "Not authenticated"}), 401

            # Get user credentials and profile
            profile = await db_service.get_user_profile(user_id)
            if not profile:
                return jsonify({"error": "User not found"}), 404

            # Get credentials for additional info
            credentials = None
            # We need to get credentials by user_id, but we only have username lookup
            # Let's add the username to the profile response
            # For now, get credentials separately if needed

            return (
                jsonify(
                    {
                        "user_id": profile.user_id,
                        "name": profile.name,
                        "status": profile.status.value,
                        "created_at": profile.created_at.isoformat(),
                        "updated_at": profile.updated_at.isoformat(),
                    }
                ),
                200,
            )

        except Exception as e:
            logger.error(f"Get current user error: {e}", exc_info=True)
            return jsonify({"error": "Internal server error"}), 500

    @auth_bp.route("/logout", methods=["POST"])
    async def logout():
        """
        Logout user (client-side token deletion).

        Note: With JWT, logout is primarily client-side.
        This endpoint exists for future token blacklist implementation.

        Returns:
            200: Logout successful
        """
        return jsonify({"message": "Logout successful"}), 200

    return auth_bp
