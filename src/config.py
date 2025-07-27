import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration settings for the application."""
    
    # LLM Configuration
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    
    # Database Configuration
    DATABASE_PATH = os.path.join(os.path.dirname(__file__), "data", "psychoanalyst.db")
    
    # Vector Database Configuration
    VECTOR_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "vector_db")
    
    # Domain Knowledge Configuration
    DOMAIN_KNOWLEDGE_PATH = os.path.join(os.path.dirname(__file__), "data", "domain_knowledge")
    
    # Application Configuration
    APP_NAME = "Virtual LLM-Driven Psychoanalyst"
    VERSION = "0.1.0"
