import logging
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings using pydantic-settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra fields from environment variables
    )

    # Application Configuration
    APP_NAME: str = "Virtual LLM-Driven Psychoanalyst"
    VERSION: str = "0.1.0"

    # LLM Configuration
    GOOGLE_API_KEY: str = Field(default="")
    MODEL_NAME: str = Field(
        default="gemini-2.5-flash", description="Google Gemini model to use"
    )

    # Agent-Specific LLM Models (Optional - defaults to MODEL_NAME)
    INTAKE_MODEL: str = Field(
        default="", description="Model for intake agent (defaults to MODEL_NAME)"
    )
    ASSESSMENT_MODEL: str = Field(
        default="", description="Model for assessment agent (defaults to MODEL_NAME)"
    )
    PSYCHOANALYST_MODEL: str = Field(
        default="",
        description="Model for psychoanalyst agent (defaults to MODEL_NAME)",
    )
    REFLECTION_MODEL: str = Field(
        default="", description="Model for reflection agent (defaults to MODEL_NAME)"
    )
    MEMORY_MODEL: str = Field(
        default="", description="Model for memory agent (defaults to MODEL_NAME)"
    )
    PLANNING_MODEL: str = Field(
        default="", description="Model for planning agent (defaults to MODEL_NAME)"
    )

    # LLM Rate Limiting Configuration
    LLM_RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        description="Enable rate limiting for LLM API calls",
    )
    LLM_REQUESTS_PER_MINUTE: float = Field(
        default=5.0,
        ge=0.1,
        le=1000.0,
        description="Maximum LLM requests per minute (Gemini free tier: 5/min)",
    )
    LLM_BURST_CAPACITY: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum burst requests (concurrent capacity)",
    )

    # Database Configuration
    DATABASE_PATH: str = Field(default="data/psychoanalyst.db")

    # Vector Database Configuration
    VECTOR_DB_PATH: str = Field(default="data/vector_db")

    # Domain Knowledge Configuration
    DOMAIN_KNOWLEDGE_PATH: str = Field(default="data/domain_knowledge")

    # Embedding Configuration
    USE_ONNX_EMBEDDINGS: bool = Field(
        default=True, description="Use ONNX backend for faster embedding inference"
    )
    EMBEDDING_MODEL_NAME: str = Field(
        default="all-MiniLM-L6-v2", description="Sentence transformer model name"
    )

    # Session Configuration
    SESSION_DURATION_MINUTES: int = Field(default=45)

    # Test Configuration
    TEST_DATABASE_PATH: str = Field(default="data/psychoanalyst_test.db")
    TEST_SESSION_DURATION_MINUTES: int = Field(default=1)

    # Intake Session Topics
    INTAKE_TOPICS: list[str] = [
        "Presenting Problem",
        "Current Symptoms",
        "Personal History",
        "Family Background",
        "Relationships",
        "Work/School",
        "Physical Health",
        "Mental Health History",
        "Substance Use",
        "Coping Mechanisms",
        "Support System",
        "Goals for Therapy",
    ]

    # Environment
    APP_ENV: str = Field(default="production")

    # Authentication Configuration
    JWT_SECRET_KEY: str = Field(
        default="",
        description=(
            "Secret key for JWT token encoding/decoding " "(MUST be set in production)"
        ),
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60, description="JWT token expiration in minutes"
    )
    REQUIRE_AUTHENTICATION: bool = Field(
        default=True, description="Whether authentication is required"
    )
    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:5173"],
        description="List of allowed CORS origins",
    )

    # Logging Configuration
    LOG_LEVEL: str = Field(default="INFO")
    CONSOLE_LOG_LEVEL: str = Field(default="CRITICAL")
    LOG_FORMAT: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Database Configuration
    DATABASE_POOL_SIZE: int = Field(default=5, ge=1, le=20)
    DATABASE_POOL_TIMEOUT: int = Field(default=30)

    # Performance Configuration
    MAX_CONCURRENT_SESSIONS: int = Field(default=10)
    SESSION_TIMEOUT_MINUTES: int = Field(default=60)

    # Session Resumption Configuration
    BRIEFING_VALIDITY_DAYS: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Number of days a briefing is considered fresh",
    )
    STALE_BRIEFING_DAYS: int = Field(
        default=90,
        ge=1,
        le=730,
        description="Days after which briefing is considered stale",
    )

    # Session Resumption Content Limits
    MAX_CONTINUITY_POINTS: int = Field(default=10, ge=1, le=20)
    MAX_PROGRESS_HIGHLIGHTS: int = Field(default=10, ge=1, le=20)
    MAX_UNRESOLVED_ISSUES: int = Field(default=10, ge=1, le=20)
    MAX_KEY_THEMES: int = Field(default=10, ge=1, le=20)
    MAX_SUGGESTED_QUESTIONS: int = Field(default=3, ge=1, le=5)
    MAX_SESSION_GOALS: int = Field(default=3, ge=1, le=5)

    # Session Resumption Quality Constraints
    MIN_NARRATIVE_LENGTH: int = Field(default=50, ge=20)
    MAX_NARRATIVE_LENGTH: int = Field(default=1500, le=3000)
    MAX_OBSERVATIONS_LENGTH: int = Field(default=1000, le=2000)
    MAX_PLAN_NOTES_LENGTH: int = Field(default=1000, le=2000)


# Create global settings instance
settings = Settings()


def setup_logging(log_level: str = None, console_log_level: str = None) -> None:
    """
    Configure application-wide logging with separate console and file logging.

    Args:
        log_level: Optional log level override for file logging
        console_log_level: Log level for console output (uses config default: CRITICAL)
    """
    if log_level is None:
        log_level = settings.LOG_LEVEL
    if console_log_level is None:
        console_log_level = settings.CONSOLE_LOG_LEVEL

    # Create logs directory if it doesn't exist
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # Create formatters
    file_formatter = logging.Formatter(settings.LOG_FORMAT)
    console_formatter = logging.Formatter("%(levelname)s: %(message)s")

    # Create handlers
    file_handler = logging.FileHandler(logs_dir / "app.log", mode="a")
    file_handler.setLevel(getattr(logging, log_level.upper()))
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, console_log_level.upper()))
    console_handler.setFormatter(console_formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove any existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Add our handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Set specific loggers to appropriate levels
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
