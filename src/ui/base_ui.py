"""Abstract base class for UI implementations in the Virtual LLM-Driven Psychoanalyst application."""

from abc import ABC, abstractmethod


class BaseUI(ABC):
    """Abstract base class defining the UI interface for the psychoanalyst application.

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
    async def get_user_input(self, prompt: str | None = None) -> str:
        """Get input from the user.

        Args:
            prompt: Optional prompt to display to the user

        Returns:
            The user's input as a string
        """
        pass

    @abstractmethod
    async def display_system_status(self, status: str) -> None:
        """Log a technical system status message (file only).

        Args:
            status: The status message to log
        """
        pass

    @abstractmethod
    async def display_user_message(self, message: str) -> None:
        """Display a user-facing message in console.

        Args:
            message: The message to display to the user
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
