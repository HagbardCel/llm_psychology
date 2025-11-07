#!/usr/bin/env python3
"""
Server entry point for the Virtual LLM-Driven Psychoanalyst application.
Starts the unified HTTP API + WebSocket server for client connections.
"""

import sys
import os
import asyncio
import logging

# Add the src directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config, setup_logging
from unified_server import run_unified_server

# Set up logging using centralized configuration
setup_logging()
logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the server."""
    logger.info(f"Starting {Config.APP_NAME} v{Config.VERSION} - Server Mode")

    # Get configuration from environment
    host = os.getenv('SERVER_HOST', '0.0.0.0')
    port = int(os.getenv('SERVER_PORT', '8000'))

    print(f"🧠 {Config.APP_NAME} - Server Mode")
    print("=" * 60)
    print(f"Version: {Config.VERSION}")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print("=" * 60)
    print()

    try:
        # Run the unified server
        await run_unified_server(Config, host, port)

    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
        logger.info("Server terminated by user")
    except Exception as e:
        print(f"\n❌ Server error: {e}")
        logger.error(f"Server error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
