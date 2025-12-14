"""
Version checking for console client.

Verifies compatibility with backend API version before starting the client.
"""

import logging
from typing import Dict, Tuple
import httpx

logger = logging.getLogger(__name__)

# Console client version (should match backend API version format)
CLIENT_VERSION = "1.0.0"
CLIENT_TYPE = "console"


class VersionCheckError(Exception):
    """Raised when version check fails or versions are incompatible."""

    pass


async def check_backend_version(
    base_url: str, timeout: float = 5.0
) -> Tuple[bool, str]:
    """
    Check compatibility with backend API version.

    Args:
        base_url: Backend API base URL (e.g., 'http://localhost:8000')
        timeout: Request timeout in seconds

    Returns:
        Tuple of (is_compatible, message)

    Raises:
        VersionCheckError: If version check request fails
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # First, get backend version info
            version_url = f"{base_url}/api/version"
            response = await client.get(version_url)

            if response.status_code != 200:
                raise VersionCheckError(
                    f"Failed to get version info from backend: {response.status_code}"
                )

            version_info = response.json()
            api_version = version_info.get("api_version", "unknown")
            min_client_version = version_info.get("min_client_version", "unknown")

            logger.info(
                f"Backend API version: {api_version}, "
                f"Minimum client version: {min_client_version}"
            )

            # Now check compatibility
            check_url = f"{base_url}/api/version/check"
            check_response = await client.post(
                check_url,
                json={"client_version": CLIENT_VERSION, "client_type": CLIENT_TYPE},
            )

            if check_response.status_code != 200:
                raise VersionCheckError(
                    f"Failed to check version compatibility: {check_response.status_code}"
                )

            check_result = check_response.json()
            compatible = check_result.get("compatible", False)
            message = check_result.get("message", "Unknown compatibility status")
            upgrade_required = check_result.get("upgrade_required", False)
            upgrade_recommended = check_result.get("upgrade_recommended", False)

            # Log result
            if compatible:
                if upgrade_recommended:
                    logger.warning(f"Version check: {message}")
                else:
                    logger.info(f"Version check: {message}")
            else:
                logger.error(f"Version check failed: {message}")

            return compatible, message

    except httpx.TimeoutException:
        error_msg = f"Timeout connecting to backend at {base_url}"
        logger.error(error_msg)
        raise VersionCheckError(error_msg)
    except httpx.RequestError as e:
        error_msg = f"Failed to connect to backend at {base_url}: {e}"
        logger.error(error_msg)
        raise VersionCheckError(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error during version check: {e}"
        logger.error(error_msg)
        raise VersionCheckError(error_msg)


def print_version_banner(client_version: str, api_version: str):
    """
    Print a version information banner.

    Args:
        client_version: Console client version
        api_version: Backend API version
    """
    print()
    print("═" * 60)
    print("  🔍 VERSION INFORMATION")
    print("═" * 60)
    print(f"  Console Client: v{client_version}")
    print(f"  Backend API:    v{api_version}")
    print("═" * 60)
    print()


def print_version_error(message: str):
    """
    Print a version compatibility error message.

    Args:
        message: Error message to display
    """
    print()
    print("═" * 60)
    print("  ⚠️  VERSION COMPATIBILITY ERROR")
    print("═" * 60)
    print(f"  {message}")
    print()
    print("  Please update your console client to continue.")
    print("  Visit: https://github.com/your-repo/releases")
    print("═" * 60)
    print()


def print_version_warning(message: str):
    """
    Print a version compatibility warning message.

    Args:
        message: Warning message to display
    """
    print()
    print("─" * 60)
    print("  ℹ️  VERSION UPDATE AVAILABLE")
    print("─" * 60)
    print(f"  {message}")
    print()
    print("  Consider updating for the latest features.")
    print("  Visit: https://github.com/your-repo/releases")
    print("─" * 60)
    print()
