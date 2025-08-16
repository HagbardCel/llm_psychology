import os
import logging
import sys
from pathlib import Path
from typing import List, ClassVar
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    """Application configuration settings using pydantic-settings."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Ignore extra fields from environment variables
    )
    
    # Application Configuration
    APP_NAME: str = "Virtual LLM-Driven Psychoanalyst"
    VERSION: str = "0.1.0"
    
    # LLM Configuration
    GOOGLE_API_KEY: str = Field(default="")
    
    # Database Configuration
    DATABASE_PATH: str = Field(default="data/psychoanalyst.db")
    
    # Vector Database Configuration
    VECTOR_DB_PATH: str = Field(default="data/vector_db")
    
    # Domain Knowledge Configuration
    DOMAIN_KNOWLEDGE_PATH: str = Field(default="data/domain_knowledge")
    
    # Session Configuration
    SESSION_DURATION_MINUTES: int = Field(default=45)
    
    # Test Configuration
    TEST_DATABASE_PATH: str = Field(default="data/psychoanalyst_test.db")
    TEST_SESSION_DURATION_MINUTES: int = Field(default=1)
    
    # Intake Session Topics
    INTAKE_TOPICS: List[str] = [
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
        "Goals for Therapy"
    ]
    
    # Environment
    APP_ENV: str = Field(default="production")
    
    # Logging Configuration
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FORMAT: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    # Database Configuration
    DATABASE_POOL_SIZE: int = Field(default=5, ge=1, le=20)
    DATABASE_POOL_TIMEOUT: int = Field(default=30)
    
    # Performance Configuration
    MAX_CONCURRENT_SESSIONS: int = Field(default=10)
    SESSION_TIMEOUT_MINUTES: int = Field(default=60)

# Create global settings instance
settings = Settings()

# For backward compatibility, create a Config class that mimics the old interface
class Config:
    APP_NAME = settings.APP_NAME
    VERSION = settings.VERSION
    GOOGLE_API_KEY = settings.GOOGLE_API_KEY
    DATABASE_PATH = settings.TEST_DATABASE_PATH if settings.APP_ENV == "testing" else settings.DATABASE_PATH
    VECTOR_DB_PATH = settings.VECTOR_DB_PATH
    DOMAIN_KNOWLEDGE_PATH = settings.DOMAIN_KNOWLEDGE_PATH
    SESSION_DURATION_MINUTES = settings.TEST_SESSION_DURATION_MINUTES if settings.APP_ENV == "testing" else settings.SESSION_DURATION_MINUTES
    INTAKE_TOPICS = settings.INTAKE_TOPICS
    TEST_DATABASE_PATH = settings.TEST_DATABASE_PATH
    TEST_SESSION_DURATION_MINUTES = settings.TEST_SESSION_DURATION_MINUTES
    APP_ENV = settings.APP_ENV
    LOG_LEVEL = settings.LOG_LEVEL
    LOG_FORMAT = settings.LOG_FORMAT
    DATABASE_POOL_SIZE = settings.DATABASE_POOL_SIZE
    DATABASE_POOL_TIMEOUT = settings.DATABASE_POOL_TIMEOUT
    MAX_CONCURRENT_SESSIONS = settings.MAX_CONCURRENT_SESSIONS
    SESSION_TIMEOUT_MINUTES = settings.SESSION_TIMEOUT_MINUTES


def setup_logging(log_level: str = None) -> None:
    """
    Configure application-wide logging.
    
    Args:
        log_level: Optional log level override
    """
    if log_level is None:
        log_level = settings.LOG_LEVEL
    
    # Create logs directory if it doesn't exist
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=settings.LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(logs_dir / "app.log", mode="a")
        ]
    )
    
    # Set specific loggers to appropriate levels
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
