"""Custom exceptions for the psychoanalyst application."""

class PsychoanalystError(Exception):
    """Base exception for psychoanalyst application."""
    pass

class DatabaseError(PsychoanalystError):
    """Raised when database operations fail."""
    pass

class SessionNotFoundError(DatabaseError):
    """Raised when a session cannot be found."""
    pass

class TherapyPlanCreationError(DatabaseError):
    """Raised when therapy plan creation fails."""
    pass

class LLMServiceError(PsychoanalystError):
    """Raised when LLM service calls fail."""
    pass

class RAGServiceError(PsychoanalystError):
    """Raised when RAG service operations fail."""
    pass

class ConfigurationError(PsychoanalystError):
    """Raised when configuration is invalid or missing."""
    pass

class AgentError(PsychoanalystError):
    """Raised when agent operations fail."""
    pass

class IntakeError(AgentError):
    """Raised when intake agent operations fail."""
    pass

class AssessmentError(AgentError):
    """Raised when assessment agent operations fail."""
    pass

class PsychoanalystAgentError(AgentError):
    """Raised when psychoanalyst agent operations fail."""
    pass

class ReflectionError(AgentError):
    """Raised when reflection agent operations fail."""
    pass

class StyleServiceError(PsychoanalystError):
    """Raised when style service operations fail."""
    pass

class UIError(PsychoanalystError):
    """Raised when UI operations fail."""
    pass
