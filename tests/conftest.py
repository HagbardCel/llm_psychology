import os
import sys
from unittest.mock import Mock

import pytest

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Import after path manipulation
from context.user_context import UserContext
from models.data_models import Message, Session, TherapyPlan, UserProfile

# Note: DatabaseService and db_service fixture removed (obsolete asyncio version)
# Trio tests use trio_db_service fixture instead (see app_config fixture below)


@pytest.fixture(autouse=True)
def mock_google_api_key(monkeypatch):
    """
    Automatically mock GOOGLE_API_KEY for all tests to prevent
    configuration errors.
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "test_mock_api_key_for_testing")
    # Also set other optional env vars that might be checked
    monkeypatch.setenv("GEMINI_MODEL", "gemini-1.5-flash")
    monkeypatch.setenv("DATABASE_PATH", ":memory:")
    return "test_mock_api_key_for_testing"


@pytest.fixture
def mock_llm_service():
    """Create a mock LLMService for testing."""
    import json

    llm_service = Mock()

    # Return valid JSON for session briefing generation
    # Note: generated_at, session_count, last_session_id are added by agent automatically
    briefing_response = {
        "briefing_type": "resumption",
        "last_session_date": "2025-01-01",  # Required field
        "narrative_handoff": (
            "Mock session narrative for testing purposes with "
            "sufficient length to meet validation"
        ),
        "patient_observations": "Patient was engaged and communicative during session",
        "plan_progression_notes": "Session progressed well according to treatment plan",
        "relationship_quality": "developing",
        "continuity_points": ["Follow up on main topic", "Explore deeper issue"],
        "emotional_summary": {
            "last_session": "calm and engaged",
            "trend": "stable",
            "note": "Patient showing good progress",
        },
        "key_themes": [
            {
                "theme": "anxiety",
                "status": "ongoing",
                "priority": "high",
                "frequency": 3,
                "first_appearance": "session_001",
                "last_discussed": "session_003",
            }
        ],
        "progress_highlights": ["Made progress on identifying triggers"],
        "unresolved_issues": ["Underlying perfectionism"],
        "recommended_approach": {
            "opening_tone": "Warm and supportive",
            "opening_focus": "Check in on progress",
            "things_to_avoid": "Being too direct",
            "suggested_questions": ["How have you been feeling?"],
            "therapeutic_goals_for_session": ["Build on previous insights"],
        },
    }

    llm_service.generate_response = Mock(return_value=json.dumps(briefing_response))

    # Enhanced structured response with common fields used by agents
    def mock_structured_response(prompt, output_format=None):
        """Return structured response based on what agents typically request."""
        # Default response structure
        response_data = {
            "test": "response",
            "key_themes": ["anxiety", "work_stress", "coping"],
            "emotional_state": "anxious",
            "progress_indicators": ["engagement", "insight"],
            "recommended_approaches": ["CBT", "mindfulness"],
        }
        return {"raw_response": str(response_data)}

    llm_service.generate_structured_response = Mock(
        side_effect=mock_structured_response
    )

    # Add streaming support - returns list of chunks (not async generator)
    async def mock_stream_response(*args, **kwargs):
        """Mock streaming response that returns chunks as a list."""
        return ["Hello ", "there! ", "This ", "is ", "a ", "mock ", "response."]

    llm_service.generate_response_stream = mock_stream_response

    # Add async versions that wrap the sync mocks
    async def mock_generate_response_async(prompt, context=None):
        return llm_service.generate_response(prompt, context)

    llm_service.generate_response_async = mock_generate_response_async

    async def mock_generate_structured_response_async(prompt, output_format=None):
        return llm_service.generate_structured_response(prompt, output_format)

    llm_service.generate_structured_response_async = (
        mock_generate_structured_response_async
    )

    return llm_service


@pytest.fixture
def mock_rag_service():
    """Create a mock RAGService for testing."""
    rag_service = Mock()

    def retrieve_relevant_knowledge(*args, **kwargs):
        print("DEBUG: mock retrieve_relevant_knowledge called")
        return [{"content": "Mock knowledge", "source": "test.md"}]

    rag_service.retrieve_relevant_knowledge = retrieve_relevant_knowledge

    rag_service.get_knowledge_by_source = Mock(
        return_value=[{"content": "Mock knowledge", "source": "test.md"}]
    )
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
        updated_at="2024-01-01T00:00:00",
    )


@pytest.fixture
def sample_session():
    """Create a sample session for testing."""
    return Session(
        session_id="test_session_123",
        user_id="test_user_123",
        timestamp="2024-01-01T00:00:00",
        transcript=[
            Message(
                role="user",
                content="Hello, I'd like to discuss my thoughts.",
                timestamp="2024-01-01T00:00:00",
            ),
            Message(
                role="assistant",
                content="Hello! I'm here to help you explore your thoughts and feelings.",
                timestamp="2024-01-01T00:00:01",
            ),
            Message(
                role="user",
                content="I've been feeling stressed about work lately.",
                timestamp="2024-01-01T00:00:02",
            ),
            Message(
                role="assistant",
                content=(
                    "I understand. Work stress can be challenging. "
                    "Can you tell me more about what's been bothering you?"
                ),
                timestamp="2024-01-01T00:00:03",
            ),
        ],
        topics=[],
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
            "themes": "Work stress, anxiety, coping mechanisms",
        },
        version=1,
        selected_therapy_style="cbt",
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


# Note: intake_agent, test_server, and websocket_client fixtures removed
# (obsolete asyncio fixtures referencing deleted IntakeAgent and UnifiedServer)
# Trio tests use their own fixtures in test_trio_*.py files


@pytest.fixture
def test_config():
    """Create test configuration."""
    from config import settings

    # We can't easily modify the global settings object safely for tests
    # without side effects. But for now we'll just return the settings
    # object as is, assuming it's configured correctly or we'd need a way
    # to override it. For backward compatibility with tests expecting a
    # Config object with attributes:
    return settings


@pytest.fixture
def app_config(tmp_path):
    """Create test configuration for Trio tests (alias for test_config)."""
    from config import settings

    # Use temporary file for test database (in-memory doesn't work well
    # with Trio's threading)
    test_db_path = str(tmp_path / "test_trio.db")

    # We need to patch the settings object or create a mock that looks like it
    # Since settings is a Pydantic model, we can use model_copy to create a modified version
    # BUT, the code uses the global 'settings' object usually.
    # However, the ServiceContainer takes a config object.

    # Create a mock or modified copy
    mock_settings = settings.model_copy(
        update={
            "DATABASE_PATH": test_db_path,
            "GOOGLE_API_KEY": "test_key_not_used",
        }
    )
    return mock_settings


@pytest.fixture
async def trio_db_service(app_config):
    """Create a TrioDatabaseService with in-memory database for testing."""
    from services.migration_service import MigrationService
    from services.trio_db_service import TrioDatabaseService

    # Use shared cache from config so tables persist across connections
    migration_service = MigrationService(app_config)
    db = TrioDatabaseService(app_config.DATABASE_PATH, migration_service)
    await db.initialize()

    yield db

    # Cleanup
    await db.clear_all_data()


@pytest.fixture
async def mock_service_container(app_config, mock_llm_service, mock_rag_service):
    """Create a ServiceContainer with mocked LLM and RAG services for Trio tests."""
    from container.service_container import ServiceContainer

    container = ServiceContainer(app_config)

    # Register mocks BEFORE any get() calls to prevent real service creation
    container.register("llm_service", mock_llm_service)
    container.register("rag_service", mock_rag_service)

    # Initialize database service
    trio_db_service = container.get("trio_db_service")
    await trio_db_service.initialize()

    yield container

    # Cleanup
    await trio_db_service.clear_all_data()


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--no-mocks",
        action="store_true",
        default=False,
        help="Run tests with real LLM and RAG services (no mocks)",
    )


@pytest.fixture
def use_real_llm(request):
    """Fixture to check if real LLM should be used."""
    return request.config.getoption("--no-mocks")
