import os
from unittest.mock import Mock

import pytest
from datetime import datetime

# NOTE: Do not import app modules at top-level unless needed for fixtures.
# This file is imported by pytest during collection.


def _get_free_tcp_port(host: str = "127.0.0.1") -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.data_models import Message, Session, TherapyPlan, UserProfile

# Note: DatabaseService and db_service fixture removed (obsolete asyncio version)
# Trio tests use trio_db_service fixture instead (see app_config fixture below)


@pytest.fixture(autouse=True)
def mock_google_api_key(monkeypatch, request):
    """
    Automatically mock GOOGLE_API_KEY for all tests to prevent
    configuration errors, UNLESS --no-mocks is specified.
    """
    if request.config.getoption("--no-mocks"):
        return None

    monkeypatch.setenv("GOOGLE_API_KEY", "test_mock_api_key_for_testing")
    # Also set other optional env vars that might be checked
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setenv("DATABASE_PATH", ":memory:")
    return "test_mock_api_key_for_testing"


@pytest.fixture
def mock_llm_service():
    """Create a mock LLMService for testing."""
    import json
    from datetime import datetime

    from pydantic import BaseModel

    llm_service = Mock()

    llm_service.generate_response = Mock(return_value="Mock response")

    def _mock_structured_payload(prompt: str, schema: type[BaseModel]) -> dict:
        schema_name = getattr(schema, "__name__", "")

        if schema_name == "SessionAnalysis":
            return {
                "key_themes": ["anxiety", "work stress"],
                "emotional_state": "anxious",
                "insights": ["pattern recognition"],
                "progress_indicators": ["engagement"],
            }

        if schema_name == "Tier2Enrichment":
            return {
                "psychological_summary": "Mock summary",
                "dominant_affects": ["anxiety"],
                "key_themes": ["work stress"],
                "notable_interactions": None,
                "interpretations": None,
                "patient_reactions": None,
            }

        if schema_name == "PlanUpdate":
            return {
                "focus": "Anxiety management",
                "goals": ["Reduce anxiety", "Improve sleep"],
                "techniques": ["Cognitive restructuring", "Mindfulness"],
                "themes": "Anxiety, coping, work stress",
                "timeline": "12 weeks",
            }

        if schema_name == "PatientProfileExtract":
            # Some tests assert on a specific name; pick it if it appears in the prompt.
            alias = "Alex"
            prompt_lower = prompt.lower()
            if "sarah johnson" in prompt_lower or "hello sarah" in prompt_lower:
                alias = "Sarah Johnson"
            return {
                "basic_info": {
                    "alias": alias,
                    "data_of_birth": None,
                    "gender": None,
                    "cultural_background": None,
                    "primary_language": "English",
                },
                "family": {
                    "parents": None,
                    "siblings": None,
                    "family_atmosphere": None,
                    "significant_events": None,
                },
                "history": {
                    "education": None,
                    "work_history": None,
                    "relationship_to_work": None,
                },
                "context": {
                    "relationships": None,
                    "social_context": None,
                    "current_situation": None,
                },
                "frame": {
                    "preferred_school": None,
                    "boundary_notes": None,
                    "frame_notes": None,
                },
            }

        if schema_name == "PatientAnalysis":
            return {
                "current_focus": {
                    "theme": "Work-related anxiety",
                    "salience": "Patient reports anxiety escalating in professional settings",
                },
                "transference": {
                    "idealization": None,
                    "devaluation": None,
                    "boundaries": None,
                    "other_patterns": "Developing therapeutic alliance",
                },
                "narratives": [
                    {
                        "title": "Fear of failure",
                        "description": "Recurring worry about being judged and failing",
                        "first_appeared": "intake",
                    }
                ],
                "defenses": {
                    "primary_defenses": ["intellectualization"],
                    "defensive_style": "Cerebral",
                    "flexibility": "Moderately flexible",
                },
                "orientation": {
                    "pacing": "Gradual",
                    "risk_areas": ["perfectionism"],
                    "key_questions": ["What happens internally before anxiety spikes?"],
                },
            }

        if schema_name == "Tier4Extract":
            return {
                "initial_goals": ["Reduce work-related anxiety"],
                "current_progress": "Baseline established",
                "planned_interventions": ["Supportive listening"],
                "status": "active",
            }

        if schema_name == "ChangeDetectionDecision":
            return {
                "update_needed": False,
                "change_summary": None,
                "confidence": "high",
            }

        if schema_name == "Tier1ProfilePatch":
            return {}

        if schema_name == "SessionBriefing":
            today = datetime.now()
            return {
                "briefing_type": "resumption",
                "generated_at": today.isoformat(),
                "session_count": 1,
                "last_session_id": "session_001",
                "last_session_date": today.date().isoformat(),
                "narrative_handoff": (
                    "Patient discussed work-related anxiety and stress. "
                    "We explored triggers, automatic thoughts, and early patterns. "
                    "Focus remains on building coping skills and insight."
                ),
                "patient_observations": "Patient was engaged and communicative.",
                "plan_progression_notes": "Session aligned with the current plan.",
                "relationship_quality": "developing",
                "continuity_points": ["Follow up on workplace triggers"],
                "emotional_summary": {
                    "last_session": "anxious but engaged",
                    "trend": "stable",
                    "note": "Anxiety levels steady; patient shows engagement.",
                },
                "key_themes": [
                    {
                        "theme": "work stress",
                        "status": "ongoing",
                        "priority": "high",
                        "frequency": 1,
                        "first_appearance": "session_001",
                        "last_discussed": "session_001",
                    }
                ],
                "progress_highlights": ["Identified trigger situations"],
                "unresolved_issues": ["Perfectionism"],
                "recommended_approach": {
                    "opening_tone": "Warm and supportive",
                    "opening_focus": "Check in on workplace anxiety",
                    "things_to_avoid": "Overwhelming with too many questions",
                    "suggested_questions": ["What stood out from last time?"],
                    "therapeutic_goals_for_session": ["Build on prior insights"],
                },
                "intervention_evidence": [],
            }

        # Default: minimal safe payload for schemas we don't explicitly handle.
        return {}

    def mock_structured_output(prompt, schema, method="json_schema"):
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            payload = _mock_structured_payload(prompt, schema)
            return schema.model_validate(payload)
        return {}

    llm_service.generate_structured_output = Mock(side_effect=mock_structured_output)

    # Add streaming support - returns list of chunks (not async generator)
    async def mock_stream_response(*args, **kwargs):
        """Mock streaming response that returns chunks as a list."""
        return ["Hello ", "there! ", "This ", "is ", "a ", "mock ", "response."]

    llm_service.generate_response_stream = mock_stream_response

    # Add async versions that wrap the sync mocks
    async def mock_generate_response_async(prompt, context=None, phase=None):
        return llm_service.generate_response(prompt, context)

    llm_service.generate_response_async = mock_generate_response_async

    async def mock_generate_structured_output_async(
        prompt, schema, method="json_schema", phase=None
    ):
        return llm_service.generate_structured_output(prompt, schema, method=method)

    llm_service.generate_structured_output_async = mock_generate_structured_output_async

    return llm_service


@pytest.fixture
def mock_rag_service():
    """Create a mock RAGService for testing."""
    rag_service = Mock()

    # Use Mock for retrieve_relevant_knowledge so tests can set return_value
    rag_service.retrieve_relevant_knowledge = Mock(
        return_value=[{"content": "Mock knowledge", "source": "test.md"}]
    )

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
        data_of_birth=datetime(1990, 1, 1),
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
        initial_goals=["Develop coping strategies"],
        current_progress="Baseline established",
        planned_interventions=["Cognitive restructuring"],
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
    from psychoanalyst_app.config import Settings

    return Settings()


@pytest.fixture
def app_config(tmp_path):
    """Create test configuration for Trio tests (alias for test_config)."""
    from psychoanalyst_app.config import Settings

    # Use temporary file for test database (in-memory doesn't work well
    # with Trio's threading)
    test_db_path = str(tmp_path / "test_trio.db")

    # We need to patch the settings object or create a mock that looks like it
    # Since settings is a Pydantic model, we can use model_copy to create a modified version
    # BUT, the code uses the global 'settings' object usually.
    # However, the ServiceContainer takes a config object.

    # Create a mock or modified copy
    settings = Settings()
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
    from psychoanalyst_app.services.migration_service import MigrationService
    from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

    # Use shared cache from config so tables persist across connections
    migration_service = MigrationService(app_config.DATABASE_PATH)
    db = TrioDatabaseService(app_config.DATABASE_PATH, migration_service)
    await db.initialize()

    yield db

    # Cleanup
    await db.clear_all_data()


@pytest.fixture
async def mock_service_container(app_config, mock_llm_service, mock_rag_service):
    """Create a ServiceContainer with mocked LLM and RAG services for Trio tests."""
    from psychoanalyst_app.container.service_container import ServiceContainer

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


@pytest.fixture
def test_server_config(tmp_path):
    """Create test server configuration."""
    from psychoanalyst_app.config import Settings

    # Use temporary database
    test_db_path = str(tmp_path / "test_server.db")

    settings = Settings()
    return settings.model_copy(
        update={
            "DATABASE_PATH": test_db_path,
            "CORS_ALLOWED_ORIGINS": [
                "http://localhost",
                "http://127.0.0.1",
            ],
        }
    )


@pytest.fixture
async def test_server_websocket(test_server_config, mock_llm_service, mock_rag_service):
    """Create a test server with WebSocket support for integration tests.

    Returns a dict with:
        - url: HTTP base URL (e.g., "http://127.0.0.1:12345")
        - ws_url: WebSocket URL (e.g., "ws://127.0.0.1:12345/ws")
        - db_service: TrioDatabaseService instance
        - container: ServiceContainer instance
    """
    import trio

    from psychoanalyst_app.container.service_container import ServiceContainer
    from psychoanalyst_app.trio_server import TrioServer

    # Create service container with mocked services
    container = ServiceContainer(test_server_config)
    container.register("llm_service", mock_llm_service)
    container.register("rag_service", mock_rag_service)

    # Initialize database
    trio_db_service = container.get("trio_db_service")
    await trio_db_service.initialize()

    # Create server on a free port
    port = _get_free_tcp_port("127.0.0.1")
    server = TrioServer(container, host="127.0.0.1", port=port)

    # Start server in background
    async with trio.open_nursery() as nursery:
        # Start server
        await nursery.start(server.run)

        # Verify server is actually accepting connections via health check
        import httpx

        async with httpx.AsyncClient() as client:
            for _ in range(20):  # 2 seconds max (20 * 0.1s)
                try:
                    response = await client.get(
                        f"http://{server.host}:{server.port}/health", timeout=1.0
                    )
                    if response.status_code == 200:
                        break
                except Exception:
                    pass
                await trio.sleep(0.1)
            else:
                raise RuntimeError("Server failed to respond to health checks")

        # Provide server info to test
        yield {
            "url": f"http://{server.host}:{server.port}",
            "ws_url": f"ws://{server.host}:{server.port}/ws",
            "db_service": trio_db_service,
            "container": container,
            "server": server,
        }

        # Cleanup: cancel the nursery to stop the server
        nursery.cancel_scope.cancel()


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


def pytest_collection_modifyitems(config, items):
    """
    Ensure `-m unit` / `-m integration` selections are reliable.

    Many tests live under `tests/unit/` and `tests/integration/` but are not
    explicitly decorated. We auto-mark based on path unless a test already has
    an explicit `unit` or `integration` marker.
    """

    def _has_marker(item, name: str) -> bool:
        return item.get_closest_marker(name) is not None

    for item in items:
        path = str(getattr(item, "fspath", "")).replace("\\", "/")

        if "/tests/unit/" in path:
            if not _has_marker(item, "unit") and not _has_marker(item, "integration"):
                item.add_marker(pytest.mark.unit)
            continue

        if "/tests/integration/" in path:
            if not _has_marker(item, "unit") and not _has_marker(item, "integration"):
                item.add_marker(pytest.mark.integration)

    if not config.getoption("--no-mocks"):
        skip_reason = "Real LLM tests require --no-mocks to hit live services."
        for item in items:
            if item.get_closest_marker("real_llm"):
                item.add_marker(pytest.mark.skip(reason=skip_reason))
