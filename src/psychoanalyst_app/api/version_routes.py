"""
Version negotiation API endpoints.

Provides version information and compatibility checking for clients.
These endpoints are intentionally public so clients can check compatibility.
"""

from datetime import datetime, timezone
from quart import Blueprint, jsonify, request
from pydantic import ValidationError

from psychoanalyst_app.version import API_VERSION, MIN_CLIENT_VERSION, Version
from psychoanalyst_app.models.version_models import (
    VersionInfo,
    VersionCheckRequest,
    VersionCheckResponse,
)
from psychoanalyst_app.api.cache_utils import add_cache_headers, CACHE_PRESETS

# Create blueprint
version_bp = Blueprint("version", __name__, url_prefix="/api/version")


@version_bp.route("", methods=["GET"])
async def get_version():
    """
    Get backend version information.

    This endpoint is public and returns the current API version,
    minimum supported client version, and current server time.

    Returns:
        200: Version information
    """
    version_info = VersionInfo(
        api_version=str(API_VERSION),
        min_client_version=str(MIN_CLIENT_VERSION),
        server_time=datetime.now(timezone.utc).isoformat(),
    )

    response = jsonify(version_info.model_dump())
    # Cache version info for 5 minutes (semi-static data)
    return add_cache_headers(response, **CACHE_PRESETS["static_short"]), 200


@version_bp.route("/check", methods=["POST"])
async def check_version():
    """
    Check client version compatibility.

    Clients send their version and type, and the backend responds
    with compatibility information and recommendations.

    Request body:
        {
            "client_version": "1.0.0",
            "client_type": "console" | "web"
        }

    Returns:
        200: Compatibility check result
        400: Invalid request
    """
    try:
        # Parse request
        data = await request.get_json()
        check_request = VersionCheckRequest(**data)

        # Parse versions
        try:
            client_version = Version.from_string(check_request.client_version)
        except ValueError as e:
            return (
                jsonify(
                    {
                        "error": "Invalid client version format",
                        "message": str(e),
                    }
                ),
                400,
            )

        # Check compatibility
        compatible = API_VERSION.is_compatible_with(client_version)

        # Check if client is too old (below minimum)
        upgrade_required = client_version < MIN_CLIENT_VERSION

        # Check if upgrade is recommended (client is on old minor version)
        upgrade_recommended = (
            client_version.major == API_VERSION.major
            and client_version.minor < API_VERSION.minor
            and not upgrade_required
        )

        # Generate message
        if upgrade_required:
            message = (
                f"Client version {client_version} is too old. "
                f"Minimum supported version is {MIN_CLIENT_VERSION}. "
                f"Please upgrade your client."
            )
        elif not compatible:
            message = (
                f"Client version {client_version} is not compatible with "
                f"backend API version {API_VERSION}. Major version mismatch detected."
            )
        elif upgrade_recommended:
            message = (
                f"Client version {client_version} is compatible but outdated. "
                f"Current API version is {API_VERSION}. "
                f"Consider upgrading for new features."
            )
        else:
            message = (
                f"Client version {client_version} is compatible with "
                f"backend API version {API_VERSION}."
            )

        response_data = VersionCheckResponse(
            compatible=compatible and not upgrade_required,
            api_version=str(API_VERSION),
            client_version=str(client_version),
            message=message,
            upgrade_required=upgrade_required,
            upgrade_recommended=upgrade_recommended,
        )

        response = jsonify(response_data.model_dump())
        # Cache version check results for 5 minutes (deterministic based on versions)
        return add_cache_headers(response, **CACHE_PRESETS["static_short"]), 200

    except ValidationError as e:
        return jsonify({"error": "Invalid request", "details": e.errors()}), 400
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500
