"""Console-based UI implementation for the Virtual LLM-Driven Psychoanalyst application.

DEPRECATED / TESTING ONLY
==========================

This module is NOT actively used in the console-ui service.
The actual production implementation uses ConsoleClient (console_client.py)
for WebSocket-based communication with the backend server.

This file is kept for:
- Testing purposes and reference implementation
- Potential future hybrid API/direct mode functionality
- Backward compatibility during transition

STATUS: May be removed in future iterations.

PRODUCTION USE: Use console_client.py instead.
"""

import asyncio
import logging
import os
from typing import Optional, List, Dict, Any
import aiohttp
from .base_ui import BaseUI


class ConsoleUI(BaseUI):
    """Console-based UI implementation for the psychoanalyst application."""

    def __init__(self, backend_url: Optional[str] = None) -> None:
        self._input_queue: asyncio.Queue = asyncio.Queue()
        self.logger = logging.getLogger(f"{__name__}.system_ui")
        self.backend_url = (backend_url or os.getenv('API_URL', 'http://api:8000')).rstrip('/')
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def display_message(self, role: str, text: str) -> None:
        """Display a message in the console."""
        role_display = role.upper()
        if role == "therapist":
            print(f"\033[94m{role_display}\033[0m: {text}")  # Blue
        elif role == "user":
            print(f"\033[92m{role_display}\033[0m: {text}")  # Green
        else:
            print(f"\033[93m{role_display}\033[0m: {text}")  # Yellow
            
    async def get_user_input(self, prompt: Optional[str] = None) -> str:
        """Get input from the user via console."""
        if prompt:
            print(f"{prompt}")
        
        user_input = input("\nYour response: ").strip()
        return user_input
        
    async def display_system_status(self, status: str) -> None:
        """Log a technical system status message (file only)."""
        self.logger.info(f"SYSTEM: {status}")
    
    async def display_user_message(self, message: str) -> None:
        """Display a user-facing message in console (clean, no colors)."""
        print(f"{message}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session for API calls."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _fetch_styles_from_api(self) -> List[Dict[str, Any]]:
        """Fetch available therapy styles from the backend API.

        Returns:
            List of style dictionaries with 'id', 'name', and 'description' keys.
        """
        try:
            session = await self._get_session()
            url = f"{self.backend_url}/api/therapy/styles"

            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('styles', [])
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to fetch styles: {response.status} - {error_text}")
                    print(f"⚠️  Warning: Could not fetch therapy styles from backend (HTTP {response.status})")
                    return []

        except aiohttp.ClientError as e:
            self.logger.error(f"Network error fetching styles: {e}")
            print(f"⚠️  Warning: Could not connect to backend API: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching styles: {e}")
            print(f"⚠️  Warning: Error fetching therapy styles: {e}")
            return []

    async def cleanup(self) -> None:
        """Cleanup resources (close HTTP session)."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def present_therapy_style_selection(self, recommendations: list) -> str:
        """Present therapy style recommendations and get user selection."""
        # Limit to top 3 recommendations
        top_recommendations = recommendations[:3]
        
        self.logger.info("SYSTEM: Based on our conversation, I recommend the following therapy approaches:")
        
        # Log recommendations
        for i, rec in enumerate(top_recommendations, 1):
            self.logger.info(f"SYSTEM: {i}. {rec['name']}")
            self.logger.info(f"SYSTEM:    {rec['description']}")
        
        # Add "Other" option
        self.logger.info(f"SYSTEM: {len(top_recommendations) + 1}. Other (See all available styles)")
        
        # Display recommendations to console for user selection
        print("Based on our conversation, I recommend the following therapy approaches:")
        print()
        
        for i, rec in enumerate(top_recommendations, 1):
            print(f"{i}. {rec['name']}")
            print(f"   {rec['description']}")
            print()
        
        print(f"{len(top_recommendations) + 1}. Other (See all available styles)")
        print()
        
        # Get user selection for recommendations
        while True:
            try:
                choice = input(f"Please select a therapy style (1-{len(top_recommendations) + 1}): ").strip()
                self.logger.info(f"SYSTEM: Please select a therapy style (1-{len(top_recommendations) + 1})")
                choice_num = int(choice)
                if 1 <= choice_num <= len(top_recommendations):
                    return top_recommendations[choice_num - 1]['style_id']
                elif choice_num == len(top_recommendations) + 1:
                    # Show all available styles
                    return await self._select_from_all_styles()
                else:
                    print(f"Invalid choice. Please enter a number between 1 and {len(top_recommendations) + 1}.")
            except ValueError:
                print("Invalid input. Please enter a number.")
    
    async def _select_from_all_styles(self) -> str:
        """Allow user to select from all available therapy styles."""
        # Fetch styles from the backend API
        styles_data = await self._fetch_styles_from_api()

        if not styles_data:
            print("❌ Error: Could not retrieve therapy styles from backend.")
            print("Using fallback: defaulting to 'freud' style.")
            self.logger.error("Failed to fetch styles, defaulting to 'freud'")
            return 'freud'

        self.logger.info("SYSTEM: Here are all available therapy styles:")

        # Build style options from API response
        style_options = []
        for style in styles_data:
            style_options.append({
                "style_id": style.get('id', ''),
                "name": style.get('name', ''),
                "description": style.get('description', '')
            })
        
        # Log all styles
        for i, style in enumerate(style_options, 1):
            self.logger.info(f"SYSTEM: {i}. {style['name']}")
            self.logger.info(f"SYSTEM:    {style['description']}")
        
        # Display to console for user selection
        print("Here are all available therapy styles:")
        print()
        
        for i, style in enumerate(style_options, 1):
            print(f"{i}. {style['name']}")
            print(f"   {style['description']}")
            print()
        
        # Get user selection
        while True:
            try:
                choice = input(f"Please select a therapy style (1-{len(style_options)}): ").strip()
                self.logger.info(f"SYSTEM: Please select a therapy style (1-{len(style_options)})")
                choice_num = int(choice)
                if 1 <= choice_num <= len(style_options):
                    return style_options[choice_num - 1]['style_id']
                else:
                    print(f"Invalid choice. Please enter a number between 1 and {len(style_options)}.")
            except ValueError:
                print("Invalid input. Please enter a number.")
        
    async def run(self) -> None:
        """Run the console UI application."""
        try:
            # For console UI, this is a no-op since we don't need an event loop
            pass
        finally:
            # Ensure cleanup is called
            await self.cleanup()
