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
import uuid

# Import directly from the package
from src.console_client import ConsoleClient
from src.version_check import (
    check_backend_version,
    print_version_error,
    print_version_warning,
    VersionCheckError,
    CLIENT_VERSION,
)


# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point for console UI client."""
    logger.info("Starting Console UI Client for Virtual LLM-Driven Psychoanalyst")

    # Configuration
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
    websocket_url = os.getenv(
        "WEBSOCKET_URL", "http://localhost:8000"
    )  # Unified server on same port

    print("🧠 Virtual LLM-Driven Psychoanalyst - Console Interface")
    print("=" * 60)
    print(f"Backend: {backend_url}")
    print(f"WebSocket: {websocket_url}")
    print(f"Client Version: v{CLIENT_VERSION}")
    print("=" * 60)
    print()

    try:
        # Check version compatibility
        print("🔍 Checking backend compatibility...")
        try:
            compatible, message = await check_backend_version(backend_url)

            if not compatible:
                print_version_error(message)
                logger.error("Version compatibility check failed - exiting")
                return 1
            else:
                print("✅ Version check passed")
                # Show warning if upgrade is recommended (message contains "outdated")
                if (
                    "outdated" in message.lower()
                    or "consider upgrading" in message.lower()
                ):
                    print_version_warning(message)
                print()
        except VersionCheckError as e:
            logger.warning(f"Version check failed: {e}")
            print(f"⚠️  Could not verify version compatibility: {e}")
            print("Continuing anyway (use at your own risk)...")
            print()

        user_id = os.getenv("USER_ID") or uuid.uuid4().hex
        logger.info("Using user_id: %s", user_id)
        print(f"ℹ️  Using user_id: {user_id}")
        print()

        # Initialize console client
        client = ConsoleClient(
            backend_url=backend_url,
            websocket_url=websocket_url,
            user_id=user_id,
        )

        # Start the console interface
        await client.run()

    except KeyboardInterrupt:
        print("\n\n👋 Goodbye! Take care of yourself.")
        logger.info("Console UI client terminated by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.error(f"Console UI client error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(trio.run(main))
