import sys
import os
import tempfile
import pytest
import sqlite3
from unittest.mock import Mock, AsyncMock

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import after path manipulation
from config import Config
from services.db_service import DatabaseService
from services.llm_service import LLMService
from services.rag_service import RAGService
from context.user_context import UserContext
from models.data_models import Session, Message, TherapyPlan, UserProfile, Topic

@pytest.fixture
def temp_db_path():
    """Create a temporary database file for testing."""
    temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    temp_db.close()
    yield temp_db.name
    os.unlink(temp_db.name)

@pytest.fixture
def db_service(temp_db_path):
    """Create a DatabaseService instance with a temporary database."""
    # Create a simple config mock for testing
    class MockConfig:
        DATABASE_PATH = temp_db_path
    
    # Use the mock config
    db = DatabaseService(temp_db_path)
    yield db

@pytest.fixture
def mock_llm_service():
    """Create a mock LLMService for testing."""
    llm_service = Mock()
    llm_service.generate_response = Mock(return_value="Mock LLM response")
    llm_service.generate_structured_response = Mock(return_value={"raw_response": '{"test": "response"}'})
    return llm_service

@pytest.fixture
def mock_rag_service():
    """Create a mock RAGService for testing."""
    rag_service = Mock()
    rag_service.retrieve_relevant_knowledge = Mock(return_value=[{"content": "Mock knowledge", "source": "test.md"}])
    rag_service.get_knowledge_by_source = Mock(return_value=[{"content": "Mock knowledge", "source": "test.md"}])
    return rag_service

@pytest.fixture
def sample_user_profile():
    """Create a sample user profile for testing."""
    return UserProfile(
        user_id="test_user_123",
        name="Test User",
        birthdate="1990-01-01",
        profession="Software Engineer",
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00"
    )

@pytest.fixture
def sample_session():
    """Create a sample session for testing."""
    return Session(
        session_id="test_session_123",
        user_id="test_user_123",
        timestamp="2024-01-01T00:00:00",
        transcript=[
            Message(role="user", content="Hello, I'd like to discuss my thoughts.", timestamp="2024-01-01T00:00:00"),
            Message(role="assistant", content="Hello! I'm here to help you explore your thoughts and feelings.", timestamp="2024-01-01T00:00:01"),
            Message(role="user", content="I've been feeling stressed about work lately.", timestamp="2024-01-01T00:00:02"),
            Message(role="assistant", content="I understand. Work stress can be challenging. Can you tell me more about what's been bothering you?", timestamp="2024-01-01T00:00:03")
        ],
        topics=[]
    )

@pytest.fixture
def sample_therapy_plan():
    """Create a sample therapy plan for testing."""
    return TherapyPlan(
        plan_id="test_plan_123",
        user_id="test_user_123",
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
        plan_details={
            "focus": "Work-related stress and anxiety management",
            "goals": "Develop coping strategies and identify stress triggers",
            "techniques": "Cognitive restructuring and mindfulness exercises",
            "themes": "Work stress, anxiety, coping mechanisms"
        },
        version=1,
        selected_therapy_style="cbt"
    )

class MockUI:
    """Mock UI for testing agents."""
    
    def __init__(self):
        self.displayed_messages = []
        self.user_inputs = []
        self.input_index = 0
    
    async def display_system_status(self, message):
        self.displayed_messages.append(("system", message))
    
    async def display_message(self, role, message):
        self.displayed_messages.append((role, message))
    
    async def get_user_input(self, prompt=None):
        if self.input_index < len(self.user_inputs):
            input_value = self.user_inputs[self.input_index]
            self.input_index += 1
            return input_value
        return ""

@pytest.fixture
def mock_ui():
    """Create a mock UI for testing."""
    return MockUI()

@pytest.fixture
def user_context():
    """Create a UserContext for testing."""
    return UserContext("test_user")

@pytest.fixture
def intake_agent(mock_llm_service, db_service, user_context):
    """Create an IntakeAgent instance for testing."""
    from agents.intake_agent import IntakeAgent
    return IntakeAgent(mock_llm_service, db_service, user_context)
