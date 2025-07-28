"""Console-based UI implementation for the Virtual LLM-Driven Psychoanalyst application."""

import asyncio
from typing import Optional
from ui.base_ui import BaseUI

class ConsoleUI(BaseUI):
    """Console-based UI implementation for the psychoanalyst application."""
    
    def __init__(self) -> None:
        self._input_queue: asyncio.Queue = asyncio.Queue()
        
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
            print(f"\033[93mSYSTEM\033[0m: {prompt}")
        
        user_input = input("\nYour response: ").strip()
        return user_input
        
    async def display_system_status(self, status: str) -> None:
        """Display a system status message."""
        print(f"\033[93mSYSTEM\033[0m: {status}")
        
    async def run(self) -> None:
        """Run the console UI application."""
        # For console UI, this is a no-op since we don't need an event loop
        pass
