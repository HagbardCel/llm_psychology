"""Console-based UI implementation for the Virtual LLM-Driven Psychoanalyst application."""

import asyncio
from typing import Optional
from ui.base_ui import BaseUI
from services.style_service import style_service

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
        
    async def present_therapy_style_selection(self, recommendations: list) -> str:
        """Present therapy style recommendations and get user selection."""
        # Limit to top 3 recommendations
        top_recommendations = recommendations[:3]
        
        print(f"\033[93mSYSTEM\033[0m: Based on our conversation, I recommend the following therapy approaches:")
        print()
        
        # Display recommendations
        for i, rec in enumerate(top_recommendations, 1):
            print(f"\033[1m{i}. {rec['name']}\033[0m")
            print(f"   {rec['description']}")
            print()
        
        # Add "Other" option
        print(f"\033[1m{len(top_recommendations) + 1}. Other (See all available styles)\033[0m")
        print()
        
        # Get user selection for recommendations
        while True:
            try:
                choice = input(f"\033[93mSYSTEM\033[0m: Please select a therapy style (1-{len(top_recommendations) + 1}): ").strip()
                choice_num = int(choice)
                if 1 <= choice_num <= len(top_recommendations):
                    return top_recommendations[choice_num - 1]['style_id']
                elif choice_num == len(top_recommendations) + 1:
                    # Show all available styles
                    return await self._select_from_all_styles()
                else:
                    print(f"\033[91mInvalid choice. Please enter a number between 1 and {len(top_recommendations) + 1}.\033[0m")
            except ValueError:
                print(f"\033[91mInvalid input. Please enter a number.\033[0m")
    
    async def _select_from_all_styles(self) -> str:
        """Allow user to select from all available therapy styles."""
        available_styles = style_service.get_available_styles()
        
        print(f"\033[93mSYSTEM\033[0m: Here are all available therapy styles:")
        print()
        
        # Display all styles with descriptions
        style_options = []
        for style_id in available_styles:
            description = style_service.get_style_description(style_id)
            style_options.append({"style_id": style_id, "name": style_id.upper(), "description": description})
        
        for i, style in enumerate(style_options, 1):
            print(f"\033[1m{i}. {style['name']}\033[0m")
            print(f"   {style['description']}")
            print()
        
        # Get user selection
        while True:
            try:
                choice = input(f"\033[93mSYSTEM\033[0m: Please select a therapy style (1-{len(style_options)}): ").strip()
                choice_num = int(choice)
                if 1 <= choice_num <= len(style_options):
                    return style_options[choice_num - 1]['style_id']
                else:
                    print(f"\033[91mInvalid choice. Please enter a number between 1 and {len(style_options)}.\033[0m")
            except ValueError:
                print(f"\033[91mInvalid input. Please enter a number.\033[0m")
        
    async def run(self) -> None:
        """Run the console UI application."""
        # For console UI, this is a no-op since we don't need an event loop
        pass
