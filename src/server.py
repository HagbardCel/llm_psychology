#!/usr/bin/env python3
"""
Server entry point for the Virtual LLM-Driven Psychoanalyst application.
Starts the unified HTTP API + WebSocket server for client connections.
"""

import logging
import os
import sys

import trio

# Add the src directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import settings, setup_logging
from trio_server import run_trio_server

# Set up logging using centralized configuration
setup_logging()
logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the server."""
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


if __name__ == "__main__":
    sys.exit(trio.run(main))
