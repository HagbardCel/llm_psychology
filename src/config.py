import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class BaseConfig:
    """Base configuration settings for the application."""
    
    # Application Configuration
    APP_NAME = "Virtual LLM-Driven Psychoanalyst"
    VERSION = "0.1.0"
    
    # LLM Configuration
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    
    # Vector Database Configuration
    VECTOR_DB_PATH = os.path.join("src", "data", "vector_db")
    
    # Domain Knowledge Configuration
    DOMAIN_KNOWLEDGE_PATH = os.path.join("src", "data", "domain_knowledge")
    
    # Intake Session Topics
    INTAKE_TOPICS = [
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

class ProdConfig(BaseConfig):
    """Production configuration settings."""
    
    # Database Configuration
    DATABASE_PATH = os.path.join("src", "data", "psychoanalyst.db")
    
    # Session Configuration
    SESSION_DURATION_MINUTES = int(os.getenv("SESSION_DURATION_MINUTES", 45))

class TestConfig(BaseConfig):
    """Test configuration settings."""
    
    # Database Configuration - separate test database
    DATABASE_PATH = os.path.join("src", "data", "psychoanalyst_test.db")
    
    # Session Configuration - shorter duration for testing
    SESSION_DURATION_MINUTES = int(os.getenv("TEST_SESSION_DURATION_MINUTES", 1))

# Determine which configuration to use based on environment variable
APP_ENV = os.getenv("APP_ENV", "production").lower()

if APP_ENV == "testing":
    Config = TestConfig
else:
    Config = ProdConfig
