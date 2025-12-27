from datetime import datetime


class UserContext:
    """
    Manages user context and session information throughout the application.

    This class replaces hardcoded user IDs and provides a centralized way
    to manage user identity and session state.
    """

    def __init__(self, user_id: str, session_id: str | None = None):
        """
        Initialize user context.

        Args:
            user_id (str): Unique identifier for the user
            session_id (Optional[str]): Optional session identifier
        """
        self.user_id = user_id
        self.session_id = session_id
        self.created_at = datetime.now()

    def create_session_context(self, session_id: str) -> "UserContext":
        """
        Create a new context with a specific session ID.

        Args:
            session_id (str): The session identifier

        Returns:
            UserContext: New context with the same user but different session
        """
        return UserContext(self.user_id, session_id)

    def __str__(self) -> str:
        """String representation for debugging."""
        session_info = f", session_id={self.session_id}" if self.session_id else ""
        return f"UserContext(user_id={self.user_id}{session_info})"

    def __repr__(self) -> str:
        """Detailed representation for debugging."""
        return self.__str__()
