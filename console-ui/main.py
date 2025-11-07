#!/usr/bin/env python3
"""
Console UI client for the Virtual LLM-Driven Psychoanalyst application.
This service connects to the backend via API and WebSocket for therapy sessions.
"""

import sys
import os
import asyncio
import logging
import json
from typing import Optional

# Import directly from the package
from src.console_client import ConsoleClient


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point for console UI client."""
    logger.info("Starting Console UI Client for Virtual LLM-Driven Psychoanalyst")
    
    # Configuration
    backend_url = os.getenv('BACKEND_URL', 'http://localhost:8000')
    websocket_url = os.getenv('WEBSOCKET_URL', 'http://localhost:8765')
    user_id = os.getenv('USER_ID', 'console_user')
    auth_token = os.getenv('AUTH_TOKEN', 'console_token')
    
    print("🧠 Virtual LLM-Driven Psychoanalyst - Console Interface")
    print("=" * 60)
    print(f"Backend: {backend_url}")
    print(f"WebSocket: {websocket_url}")
    print("=" * 60)
    print()
    
    try:
        # Initialize console client
        client = ConsoleClient(
            backend_url=backend_url,
            websocket_url=websocket_url,
            user_id=user_id,
            auth_token=auth_token
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
    sys.exit(asyncio.run(main()))
