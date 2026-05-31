"""Abstract base class for UI implementations in the Virtual LLM-Driven Therapist application."""

from abc import ABC, abstractmethod
from typing import Optional


class BaseUI(ABC):
    """Abstract base class defining the UI interface for the therapist application.

    This abstraction allows for different UI implementations (TUI, Web, etc.) to be
    swapped without changing the core application logic.
    """

    @abstractmethod
    async def display_message(self, role: str, text: str) -> None:
        """Display a message in the UI.

        Args:
            role: The role of the message sender (e.g., "user", "therapist", "system")
            text: The message content to display
        """
        pass

    @abstractmethod
    async def get_user_input(self, prompt: Optional[str] = None) -> str:
        """Get input from the user.

        Args:
            prompt: Optional prompt to display to the user

        Returns:
            The user's input as a string
        """
        pass

    @abstractmethod
    async def display_system_status(self, status: str) -> None:
        """Display a system status message.

        Args:
            status: The status message to display
        """
        pass

    @abstractmethod
    async def present_therapy_style_selection(self, recommendations: list) -> str:
        """Present therapy style recommendations and get user selection.

        Args:
            recommendations: List of therapy style recommendations with descriptions

        Returns:
            The selected therapy style ID
        """
        pass

    @abstractmethod
    async def run(self) -> None:
        """Run the UI event loop.

        This method should start the UI and handle the main application flow.
        """
        pass
