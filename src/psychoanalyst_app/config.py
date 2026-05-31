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

    # Environment
    APP_ENV: str = Field(default="production")

    # LLM Configuration
    LLM_PROVIDER: str = Field(
        default="openai_compatible",
        description=(
            "LLM provider to use: gemini, ollama, lmstudio, or openai_compatible"
        ),
    )
    LLM_BASE_URL: str = Field(
        default="",
        description=(
            "Optional LLM provider base URL. Local Docker defaults use "
            "host.docker.internal for Ollama and LM Studio."
        ),
    )
    LLM_API_KEY: str = Field(
        default="",
        description=(
            "Generic API key for OpenAI-compatible providers. Local providers "
            "can leave this unset."
        ),
    )
    GOOGLE_API_KEY: str = Field(default="", description="Primary API key for Gemini")
    GEMINI_API_KEY: str = Field(
        default="", description="Deprecated alias for GOOGLE_API_KEY"
    )
    MODEL_NAME: str = Field(
        default="local-model",
        description=(
            "Default model name when an agent-specific override is not provided "
            "(set via environment/.env files)"
        ),
    )
    INTAKE_MODEL: str = Field(
        default="", description="Model for intake agent (defaults to MODEL_NAME)"
    )
    ASSESSMENT_MODEL: str = Field(
        default="", description="Model for assessment agent (defaults to MODEL_NAME)"
    )
    THERAPIST_MODEL: str = Field(
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
    LLM_RATE_LIMIT_ENABLED: bool = Field(
        default=True, description="Enable client-side LLM rate limiting"
    )
    LLM_REQUESTS_PER_MINUTE: float = Field(
        default=2.0, description="Allowed LLM requests per minute"
    )
    LLM_BURST_CAPACITY: int = Field(
        default=2, description="Burst capacity for LLM requests"
    )
    LLM_ENABLE_THINKING: bool = Field(
        default=True,
        description=(
            "Enable model chain-of-thought / reasoning for OpenAI-compatible "
            "providers (llama.cpp, LM Studio). Ignored for Gemini and Ollama."
        ),
    )
    LLM_CALL_LOGGING_ENABLED: bool = Field(
        default=False,
        description="Enable detailed LLM call payload logging to logs/llm_calls.log",
    )
    LLM_CALL_LOGGING_REDACT: bool = Field(
        default=True,
        description="Redact prompt/response payloads in detailed LLM call logs",
    )
    LLM_CALL_LOGGING_MAX_FIELD_CHARS: int = Field(
        default=256,
        ge=64,
        le=8000,
        description="Max characters retained per logged payload field",
    )
    LLM_CALL_LOGGING_INCLUDE_CHUNKS: bool = Field(
        default=False,
        description="Include stream chunk payloads in detailed LLM logs",
    )
    LLM_METRICS_LOG_PATH: str = Field(
        default="",
        description="Optional JSONL path for prompt-free LLM timing metrics",
    )

    def model_post_init(self, __context) -> None:
        """Apply compatibility shims after settings load."""
        if not self.GOOGLE_API_KEY and self.GEMINI_API_KEY:
            object.__setattr__(self, "GOOGLE_API_KEY", self.GEMINI_API_KEY)
        normalized_provider = self.LLM_PROVIDER.strip().lower()
        object.__setattr__(self, "LLM_PROVIDER", normalized_provider)

    def get_llm_base_url(self) -> str | None:
        """Resolve the configured/default base URL for the selected LLM provider."""
        if self.LLM_BASE_URL:
            return self.LLM_BASE_URL
        if self.LLM_PROVIDER == "ollama":
            return "http://host.docker.internal:11434"
        if self.LLM_PROVIDER == "lmstudio":
            return "http://host.docker.internal:1234/v1"
        if self.LLM_PROVIDER == "openai_compatible":
            return "http://host.docker.internal:8080/v1"
        return None

    def get_model_for_agent(self, agent_type: str) -> str:
        """Resolve the configured model for a given agent."""
        agent_type = agent_type.upper()
        overrides = {
            "INTAKE": self.INTAKE_MODEL,
            "ASSESSMENT": self.ASSESSMENT_MODEL,
            "THERAPIST": self.THERAPIST_MODEL,
            "REFLECTION": self.REFLECTION_MODEL,
            "MEMORY": self.MEMORY_MODEL,
            "PLANNING": self.PLANNING_MODEL,
        }
        override = overrides.get(agent_type, "")
        model = override or self.MODEL_NAME
        if not model:
            raise ValueError(
                "MODEL_NAME must be set "
                "(or an agent-specific *_MODEL override provided)."
            )
        return model

    # Database Configuration
    DATABASE_PATH: str = Field(default="data/psychoanalyst.db")
    DATABASE_BACKUP_DIR: str = Field(default="data/backups")

    # Retrieval Configuration
    RAG_BACKEND: str = Field(
        default="none",
        description=(
            "RAG backend to use. Only 'none' is supported in the current release."
        ),
    )
    VECTOR_DB_PATH: str = Field(
        default="data/vector_db",
        description="Reserved for future local retrieval extensions.",
    )

    # Domain Knowledge Configuration
    DOMAIN_KNOWLEDGE_PATH: str = Field(
        default="data/domain_knowledge",
        description="Reserved for future local retrieval extensions.",
    )
    STYLES_DIR: str | None = Field(
        default=None,
        description="Optional override directory for therapy style packs",
    )

    # Deferred Retrieval Configuration
    USE_ONNX_EMBEDDINGS: bool = Field(
        default=True,
        description="Reserved for future local retrieval extensions.",
    )
    EMBEDDING_MODEL_NAME: str = Field(
        default="all-MiniLM-L6-v2",
        description="Reserved for future local retrieval extensions.",
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

    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:5173"],
        description="List of allowed CORS origins",
    )

    # Logging Configuration
    LOG_LEVEL: str = Field(default="INFO")
    CONSOLE_LOG_LEVEL: str = Field(default="CRITICAL")
    APP_FILE_LOGGING_ENABLED: bool = Field(
        default=False,
        description="Enable app log file output (disabled by default for local use).",
    )
    APP_FILE_LOG_PATH: str = Field(
        default="logs/app.log",
        description="Path for app log file when APP_FILE_LOGGING_ENABLED=true.",
    )
    LOG_FORMAT: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Database Configuration
    DATABASE_POOL_SIZE: int = Field(default=5, ge=1, le=20)
    DATABASE_POOL_TIMEOUT: int = Field(default=30)

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

    # Reflection Job Configuration
    REFLECTION_TIMEOUT_SECONDS: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Max time allowed for reflection before timing out.",
    )


def setup_logging(
    settings: Settings,
    log_level: str | None = None,
    console_log_level: str | None = None,
) -> None:
    """
    Configure application-wide logging with console output and optional file logs.

    Args:
        log_level: Optional log level override
        console_log_level: Log level for console output (uses config default: CRITICAL)
    """
    if log_level is None:
        log_level = settings.LOG_LEVEL
    if console_log_level is None:
        console_log_level = settings.CONSOLE_LOG_LEVEL

    # Create formatters
    file_formatter = logging.Formatter(settings.LOG_FORMAT)
    console_formatter = logging.Formatter("%(levelname)s: %(message)s")

    # Create handlers
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, console_log_level.upper()))
    console_handler.setFormatter(console_formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove any existing handlers to avoid duplicates
    root_logger.handlers.clear()

    if settings.APP_FILE_LOGGING_ENABLED:
        app_log_path = Path(settings.APP_FILE_LOG_PATH)
        app_log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(app_log_path, mode="a")
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    root_logger.addHandler(console_handler)

    # Configure dedicated LLM call logger only when explicitly enabled.
    llm_logger = logging.getLogger("llm_calls")
    llm_logger.handlers.clear()
    if settings.LLM_CALL_LOGGING_ENABLED:
        llm_log_path = Path("logs/llm_calls.log")
        llm_log_path.parent.mkdir(parents=True, exist_ok=True)
        llm_handler = logging.FileHandler(llm_log_path, mode="a")
        llm_handler.setLevel(logging.INFO)
        llm_handler.setFormatter(file_formatter)
        llm_logger.addHandler(llm_handler)
        llm_logger.setLevel(logging.INFO)
    else:
        llm_logger.addHandler(logging.NullHandler())
        llm_logger.setLevel(logging.CRITICAL)
    llm_logger.propagate = False

    metrics_logger = logging.getLogger("llm_metrics")
    metrics_logger.handlers.clear()
    if settings.LLM_METRICS_LOG_PATH:
        metrics_path = Path(settings.LLM_METRICS_LOG_PATH)
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_handler = logging.FileHandler(metrics_path, mode="a")
        metrics_handler.setLevel(logging.INFO)
        metrics_handler.setFormatter(logging.Formatter("%(message)s"))
        metrics_logger.addHandler(metrics_handler)
        metrics_logger.setLevel(logging.INFO)
    else:
        metrics_logger.addHandler(logging.NullHandler())
        metrics_logger.setLevel(logging.CRITICAL)
    metrics_logger.propagate = False

    # Set specific loggers to appropriate levels
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
