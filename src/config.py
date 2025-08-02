import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration settings for the application."""
    
    # LLM Configuration
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    
    # Database Configuration
    DATABASE_PATH = os.path.join("/app", "data", "psychoanalyst.db")
    
    # Vector Database Configuration
    VECTOR_DB_PATH = os.path.join("/app", "data", "vector_db")
    
    # Domain Knowledge Configuration
    DOMAIN_KNOWLEDGE_PATH = os.path.join("/app", "data", "domain_knowledge")
    
    # Session Configuration
    SESSION_DURATION_MINUTES = int(os.getenv("SESSION_DURATION_MINUTES", 45))
    
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
    
    # Application Configuration
    APP_NAME = "Virtual LLM-Driven Psychoanalyst"
    VERSION = "0.1.0"
