#!/usr/bin/env python3
"""
Console UI client for the Virtual LLM-Driven Psychoanalyst application.
This service connects to the backend via API and WebSocket for therapy sessions.
Trio-based implementation for structured concurrency.
"""

import sys
import os
import trio
import logging

# Import directly from the package
from src.console_client import ConsoleClient
from src.output import ConsoleOutput, setup_logging
from src.version_check import (
    check_backend_version,
    print_version_error,
    print_version_warning,
    VersionCheckError,
    CLIENT_VERSION,
)


logger = logging.getLogger(__name__)


async def main():
    """Main entry point for console UI client."""
    default_log_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "logs", "console-ui.log")
    )
    log_path = os.getenv("CONSOLE_LOG_PATH", default_log_path)
    setup_logging(log_path)
    output = ConsoleOutput(logging.getLogger("console_ui.output"))

    output.system("Starting Console UI Client for Virtual LLM-Driven Psychoanalyst")
    output.system(f"Log file: {log_path}")

    # Configuration
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
    websocket_url = os.getenv(
        "WEBSOCKET_URL", "http://localhost:8000"
    )  # Unified server on same port

    output.system("Console UI configuration:")
    output.system("🧠 Virtual LLM-Driven Psychoanalyst - Console Interface")
    output.system("=" * 60)
    output.system(f"Backend: {backend_url}")
    output.system(f"WebSocket: {websocket_url}")
    output.system(f"Client Version: v{CLIENT_VERSION}")
    output.system("=" * 60)

    try:
        # Check version compatibility
        output.system("🔍 Checking backend compatibility...")
        try:
            compatible, message = await check_backend_version(backend_url)

            if not compatible:
                print_version_error(message, output=output)
                logger.error("Version compatibility check failed - exiting")
                return 1
            else:
                output.system(f"✅ Version check passed: {message}")
                # Show warning if upgrade is recommended (message contains "outdated")
                if (
                    "outdated" in message.lower()
                    or "consider upgrading" in message.lower()
                ):
                    print_version_warning(message, output=output, log_only=True)
        except VersionCheckError as e:
            logger.warning(f"Version check failed: {e}")
            output.system(
                f"⚠️  Could not verify version compatibility: {e}. "
                "Continuing anyway (use at your own risk)..."
            )

        user_id = os.getenv("USER_ID")
        if user_id:
            logger.info("Using user_id from environment: %s", user_id)
            output.system(f"ℹ️  Using user_id from env: {user_id}")

        # Initialize console client
        client = ConsoleClient(
            backend_url=backend_url,
            websocket_url=websocket_url,
            user_id=user_id,
            output=output,
        )

        # Start the console interface
        await client.run()

    except KeyboardInterrupt:
        output.user_text("\n\n👋 Goodbye! Take care of yourself.")
        logger.info("Console UI client terminated by user")
    except Exception as e:
        output.error(f"\n❌ Error: {e}")
        logger.error(f"Console UI client error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(trio.run(main))
