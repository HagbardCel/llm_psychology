"""
Version checking for console client.

Verifies compatibility with backend API version before starting the client.
"""

import logging
from typing import Dict, Tuple, Optional
import httpx

from .output import ConsoleOutput

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


def _emit_banner(
    lines: list[str],
    output: Optional[ConsoleOutput],
    *,
    log_only: bool = False,
    is_error: bool = False,
) -> None:
    banner = "\n".join(lines)
    if output:
        if log_only:
            output.system(banner)
        elif is_error:
            output.error(banner)
        else:
            output.user_text(banner)
        return
    print(banner)


def print_version_banner(
    client_version: str,
    api_version: str,
    *,
    output: Optional[ConsoleOutput] = None,
    log_only: bool = False,
):
    """
    Print a version information banner.

    Args:
        client_version: Console client version
        api_version: Backend API version
    """
    _emit_banner(
        [
            "",
            "═" * 60,
            "  🔍 VERSION INFORMATION",
            "═" * 60,
            f"  Console Client: v{client_version}",
            f"  Backend API:    v{api_version}",
            "═" * 60,
            "",
        ],
        output,
        log_only=log_only,
    )


def print_version_error(
    message: str,
    *,
    output: Optional[ConsoleOutput] = None,
    log_only: bool = False,
):
    """
    Print a version compatibility error message.

    Args:
        message: Error message to display
    """
    _emit_banner(
        [
            "",
            "═" * 60,
            "  ⚠️  VERSION COMPATIBILITY ERROR",
            "═" * 60,
            f"  {message}",
            "",
            "  Please update your console client to continue.",
            "  Visit: https://github.com/your-repo/releases",
            "═" * 60,
            "",
        ],
        output,
        log_only=log_only,
        is_error=True,
    )


def print_version_warning(
    message: str,
    *,
    output: Optional[ConsoleOutput] = None,
    log_only: bool = False,
):
    """
    Print a version compatibility warning message.

    Args:
        message: Warning message to display
    """
    _emit_banner(
        [
            "",
            "─" * 60,
            "  ℹ️  VERSION UPDATE AVAILABLE",
            "─" * 60,
            f"  {message}",
            "",
            "  Consider updating for the latest features.",
            "  Visit: https://github.com/your-repo/releases",
            "─" * 60,
            "",
        ],
        output,
        log_only=log_only,
    )
