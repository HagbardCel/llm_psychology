import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    """Application configuration settings using pydantic-settings."""
    
    # Application Configuration
    APP_NAME: str = "Virtual LLM-Driven Psychoanalyst"
    VERSION: str = "0.1.0"
    
    # LLM Configuration
    GOOGLE_API_KEY: str = Field(default="", env="GOOGLE_API_KEY")
    
    # Database Configuration
    DATABASE_PATH: str = Field(default="src/data/psychoanalyst.db", env="DATABASE_PATH")
    
    # Vector Database Configuration
    VECTOR_DB_PATH: str = Field(default="src/data/vector_db", env="VECTOR_DB_PATH")
    
    # Domain Knowledge Configuration
    DOMAIN_KNOWLEDGE_PATH: str = Field(default="src/data/domain_knowledge", env="DOMAIN_KNOWLEDGE_PATH")
    
    # Session Configuration
    SESSION_DURATION_MINUTES: int = Field(default=45, env="SESSION_DURATION_MINUTES")
    
    # Test Configuration
    TEST_DATABASE_PATH: str = Field(default="src/data/psychoanalyst_test.db", env="TEST_DATABASE_PATH")
    TEST_SESSION_DURATION_MINUTES: int = Field(default=1, env="TEST_SESSION_DURATION_MINUTES")
    
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
    APP_ENV: str = Field(default="production", env="APP_ENV")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

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
