#!/usr/bin/env python3
"""
Server entry point for the Virtual LLM-Driven Psychoanalyst application.
Starts the unified HTTP API + WebSocket server for client connections.
"""

import logging
import os

import trio

from psychoanalyst_app.config import Settings, setup_logging
from psychoanalyst_app.trio_server import run_trio_server

logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the server."""
    settings = Settings()
    setup_logging(settings)
    logger.info(f"Starting {settings.APP_NAME} v{settings.VERSION} - Server Mode")

    # Get configuration from environment
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))

    print(f"🧠 {settings.APP_NAME} - Server Mode (Trio)")
    print("=" * 60)
    print(f"Version: {settings.VERSION}")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print("=" * 60)
    print()

    try:
        # Run the trio server
        await run_trio_server(config=settings, host=host, port=port)

    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
        logger.info("Server terminated by user")
    except Exception as e:
        print(f"\n❌ Server error: {e}")
        logger.error(f"Server error: {e}", exc_info=True)
        return 1

    return 0


def cli() -> int:
    """CLI adapter so the module can be invoked via console script."""
    return trio.run(main)


if __name__ == "__main__":
    raise SystemExit(cli())
