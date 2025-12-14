"""
Integration tests for Trio-native agents.

Tests all 6 ported agents: Memory, Planning, Intake, Reflection, Assessment, Psychoanalyst
"""

import uuid
from datetime import datetime

import pytest
import trio

from agents.trio_assessment_agent import TrioAssessmentAgent
from agents.trio_intake_agent import TrioIntakeAgent
from agents.trio_memory_agent import TrioMemoryAgent
from agents.trio_planning_agent import TrioPlanningAgent
from agents.trio_psychoanalyst_agent import TrioPsychoanalystAgent
from agents.trio_reflection_agent import TrioReflectionAgent
from container.service_container import ServiceContainer
from context.user_context import UserContext
from models.data_models import (
    Message,
    Session,
    Topic,
    UserProfile,
    UserStatus,
)
from orchestration.models import ConversationContext, WorkflowState


@pytest.fixture
async def service_container(app_config, mock_llm_service, mock_rag_service):
    """Create service container with mocked services for testing."""
    container = ServiceContainer(app_config)

    # Register mocks BEFORE any get() calls to prevent real service creation
    container.register("llm_service", mock_llm_service)
    container.register("rag_service", mock_rag_service)

    # Now safe to get trio_db_service (uses real in-memory DB)
    trio_db_service = container.get("trio_db_service")
    await trio_db_service.initialize()

    yield container

    await trio_db_service.clear_all_data()


@pytest.fixture
async def test_user(service_container):
    """Create a test user profile."""
    trio_db_service = service_container.get("trio_db_service")

    user_profile = UserProfile(
        user_id="test_user_agents",
        name="Agent Test User",
        birthdate=None,
        profession="Tester",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    await trio_db_service.save_user_profile(user_profile)
    return user_profile


@pytest.fixture
async def test_session(service_container, test_user):
    """Create a test session with transcript."""
    session_id = str(uuid.uuid4())
    session = Session(
        session_id=session_id,
        user_id=test_user.user_id,
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="user",
                content="I've been feeling anxious",
                timestamp=datetime.now(),
            ),
            Message(
                role="assistant",
                content="Tell me more about that",
                timestamp=datetime.now(),
            ),
            Message(
                role="user", content="It's mostly at work", timestamp=datetime.now()
            ),
        ],
        topics=[Topic(name="anxiety"), Topic(name="work")],
    )

    trio_db_service = service_container.get("trio_db_service")
    await trio_db_service.save_session(session)
    return session


@pytest.fixture
def user_context(test_user):
    """Create user context."""
    return UserContext(user_id=test_user.user_id)


# ===== TrioMemoryAgent Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_memory_agent_initialization(service_container, user_context):
    """Test TrioMemoryAgent initialization."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    assert memory_agent is not None
    assert str(memory_agent) == f"TrioMemoryAgent(user={user_context.user_id})"


@pytest.mark.trio
@pytest.mark.integration
async def test_memory_agent_analyze_session(
    service_container, user_context, test_session
):
    """Test session context analysis."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    # Analyze session
    context = await memory_agent.analyze_session_context(test_session)

    assert context is not None
    assert context.session_id == test_session.session_id
    assert len(context.key_themes) > 0
    assert context.emotional_state is not None


@pytest.mark.trio
@pytest.mark.integration
async def test_memory_agent_get_therapeutic_memory(
    service_container, user_context, test_session
):
    """Test therapeutic memory retrieval."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    # Get therapeutic memory
    memory = await memory_agent.get_therapeutic_memory()

    assert memory is not None
    assert memory.user_id == user_context.user_id
    assert len(memory.session_contexts) >= 0


# ===== TrioPlanningAgent Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_planning_agent_initialization(service_container, user_context):
    """Test TrioPlanningAgent initialization."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    planning_agent = TrioPlanningAgent(
        llm_service, trio_db_service, rag_service, user_context, memory_agent
    )

    assert planning_agent is not None
    assert "TrioPlanningAgent" in str(planning_agent)


@pytest.mark.trio
@pytest.mark.integration
async def test_planning_agent_create_initial_plan(
    service_container, user_context, test_session
):
    """Test creating initial therapy plan."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    planning_agent = TrioPlanningAgent(
        llm_service, trio_db_service, rag_service, user_context, memory_agent
    )

    # Create initial plan
    therapy_plan = await planning_agent.create_initial_plan(test_session, "cbt")

    assert therapy_plan is not None
    assert therapy_plan.plan_id is not None
    assert therapy_plan.user_id == user_context.user_id
    assert therapy_plan.selected_therapy_style == "cbt"
    assert therapy_plan.version == 1


# ===== TrioIntakeAgent Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_intake_agent_initialization(service_container, user_context):
    """Test TrioIntakeAgent initialization."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")

    intake_agent = TrioIntakeAgent(llm_service, trio_db_service, user_context)

    assert intake_agent is not None
    assert intake_agent.session_duration > 0
    assert len(intake_agent.intake_topics) > 0


@pytest.mark.trio
@pytest.mark.integration
async def test_intake_agent_guest_welcome_direct_response(service_container):
    """Test that guest welcome prompt is marked as direct response."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")

    # Create a guest user profile
    guest_user = UserProfile(
        user_id="guest_test_user",
        name="Guest",
        birthdate=None,
        profession="",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(guest_user)

    user_context = UserContext(user_id=guest_user.user_id)
    intake_agent = TrioIntakeAgent(llm_service, trio_db_service, user_context)

    # Create session
    session_id = str(uuid.uuid4())
    session = Session(
        session_id=session_id,
        user_id=guest_user.user_id,
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
    )
    await trio_db_service.save_session(session)

    # Create context for guest with empty message (initial greeting)
    context = ConversationContext(
        session_id=session_id,
        user_profile=guest_user,
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=60,
    )

    # Process empty message (should trigger guest welcome)
    response = await intake_agent.process_message("", context)

    # Verify response is marked as direct (not sent to LLM)
    assert response is not None
    assert response.metadata.get("is_direct_response") is True
    assert "Dr. AI" in response.content
    assert "may I have your name" in response.content
    assert response.next_action == "continue"
    assert response.next_state is None


@pytest.mark.trio
@pytest.mark.integration
async def test_intake_agent_guest_name_collection(service_container):
    """Test that guest name collection triggers state transition."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")

    # Create a guest user profile
    guest_user = UserProfile(
        user_id="guest_name_test",
        name="Guest",
        birthdate=None,
        profession="",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(guest_user)

    user_context = UserContext(user_id=guest_user.user_id)
    intake_agent = TrioIntakeAgent(llm_service, trio_db_service, user_context)

    # Create session
    session_id = str(uuid.uuid4())
    session = Session(
        session_id=session_id,
        user_id=guest_user.user_id,
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
    )
    await trio_db_service.save_session(session)

    # Create context for guest
    context = ConversationContext(
        session_id=session_id,
        user_profile=guest_user,
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=60,
    )

    # Process name message
    response = await intake_agent.process_message("John Smith", context)

    # Verify name was updated and state transitioned
    assert response is not None
    assert response.next_action == "transition"
    assert response.next_state == WorkflowState.INTAKE_IN_PROGRESS
    assert context.user_profile.name == "John Smith"
    assert context.user_profile.status == UserStatus.INTAKE_IN_PROGRESS

    # Verify profile was saved to database
    updated_profile = await trio_db_service.get_user_profile(guest_user.user_id)
    assert updated_profile.name == "John Smith"


# ===== TrioReflectionAgent Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_reflection_agent_initialization(service_container, user_context):
    """Test TrioReflectionAgent initialization."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    planning_agent = TrioPlanningAgent(
        llm_service, trio_db_service, rag_service, user_context, memory_agent
    )

    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
    )

    assert reflection_agent is not None
    assert "TrioReflectionAgent" in str(reflection_agent)


@pytest.mark.trio
@pytest.mark.integration
async def test_reflection_agent_create_initial_plan(
    service_container, user_context, test_session
):
    """Test reflection agent coordinating plan creation."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    planning_agent = TrioPlanningAgent(
        llm_service, trio_db_service, rag_service, user_context, memory_agent
    )

    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
    )

    # Create plan through reflection agent
    therapy_plan = await reflection_agent.create_initial_plan(test_session, "freud")

    assert therapy_plan is not None
    assert therapy_plan.selected_therapy_style == "freud"


# ===== TrioAssessmentAgent Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_assessment_agent_initialization(service_container, user_context):
    """Test TrioAssessmentAgent initialization."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    # Create a mock reflection agent
    reflection_agent = TrioReflectionAgent(
        llm_service, trio_db_service, rag_service, user_context, None, None
    )

    assessment_agent = TrioAssessmentAgent(
        llm_service, trio_db_service, rag_service, user_context, reflection_agent
    )

    assert assessment_agent is not None


@pytest.mark.trio
@pytest.mark.integration
async def test_assessment_agent_process_assessment(
    service_container, user_context, test_session
):
    """Test conducting assessment via orchestrator interface."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    # Create a mock reflection agent
    reflection_agent = TrioReflectionAgent(
        llm_service, trio_db_service, rag_service, user_context, None, None
    )

    assessment_agent = TrioAssessmentAgent(
        llm_service, trio_db_service, rag_service, user_context, reflection_agent
    )

    # Create context
    user_profile = await trio_db_service.get_user_profile(user_context.user_id)
    context = ConversationContext(
        session_id=test_session.session_id,
        user_profile=user_profile,
        therapy_plan=None,
        message_history=test_session.transcript,
        topics_covered=[t.name for t in test_session.topics],
        session_start_time=datetime.now(),
        duration_minutes=60,
    )

    # Process assessment
    response = await assessment_agent.process_assessment(context)

    assert response is not None
    assert response.next_action == "await_selection"
    assert "recommendations" in response.metadata
    assert len(response.metadata["recommendations"]) > 0


# ===== TrioPsychoanalystAgent Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_psychoanalyst_agent_initialization(service_container, user_context):
    """Test TrioPsychoanalystAgent initialization."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    psychoanalyst_agent = TrioPsychoanalystAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    assert psychoanalyst_agent is not None
    assert psychoanalyst_agent._get_agent_display_name() == "therapist"


# ===== Integration Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_full_agent_workflow(service_container, test_user, test_session):
    """Test complete workflow through all agents."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")
    user_context = UserContext(user_id=test_user.user_id)

    # Step 1: Memory agent analyzes session
    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )
    session_context = await memory_agent.analyze_session_context(test_session)
    assert session_context is not None

    # Step 2: Planning agent creates plan
    planning_agent = TrioPlanningAgent(
        llm_service, trio_db_service, rag_service, user_context, memory_agent
    )
    therapy_plan = await planning_agent.create_initial_plan(test_session, "cbt")
    assert therapy_plan is not None

    # Step 3: Reflection agent coordinates
    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
    )
    comprehensive_reflection = await reflection_agent.generate_comprehensive_reflection(
        test_session, therapy_plan
    )
    assert comprehensive_reflection is not None
    assert "session_context" in comprehensive_reflection

    # Step 4: Psychoanalyst agent is ready to conduct therapy
    psychoanalyst_agent = TrioPsychoanalystAgent(
        llm_service, trio_db_service, rag_service, user_context
    )
    assert psychoanalyst_agent is not None


@pytest.mark.trio
@pytest.mark.integration
async def test_concurrent_agent_operations(service_container, test_user, test_session):
    """Test concurrent operations across multiple agents."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")
    user_context = UserContext(user_id=test_user.user_id)

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )
    planning_agent = TrioPlanningAgent(
        llm_service, trio_db_service, rag_service, user_context, memory_agent
    )

    results = []

    async def analyze_session():
        context = await memory_agent.analyze_session_context(test_session)
        results.append(("analyze", context))

    async def get_memory():
        memory = await memory_agent.get_therapeutic_memory()
        results.append(("memory", memory))

    async def create_plan():
        plan = await planning_agent.create_initial_plan(test_session, "jung")
        results.append(("plan", plan))

    # Run concurrently using nursery
    async with trio.open_nursery() as nursery:
        nursery.start_soon(analyze_session)
        nursery.start_soon(get_memory)
        nursery.start_soon(create_plan)

    # Verify all completed
    assert len(results) == 3
    assert any(r[0] == "analyze" for r in results)
    assert any(r[0] == "memory" for r in results)
    assert any(r[0] == "plan" for r in results)


@pytest.mark.trio
@pytest.mark.integration
async def test_assessment_agent_process_selection(
    service_container, user_context, test_session
):
    """Test processing selection via orchestrator interface."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    # Setup dependencies for reflection agent
    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )
    planning_agent = TrioPlanningAgent(
        llm_service, trio_db_service, rag_service, user_context, memory_agent
    )
    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
    )

    assessment_agent = TrioAssessmentAgent(
        llm_service, trio_db_service, rag_service, user_context, reflection_agent
    )

    # Create context
    user_profile = await trio_db_service.get_user_profile(user_context.user_id)
    context = ConversationContext(
        session_id=test_session.session_id,
        user_profile=user_profile,
        therapy_plan=None,
        message_history=test_session.transcript,
        topics_covered=[t.name for t in test_session.topics],
        session_start_time=datetime.now(),
        duration_minutes=60,
    )

    # Process selection
    response = await assessment_agent.process_selection("cbt", context)

    assert response is not None
    assert response.next_action == "transition"
    assert response.next_state == WorkflowState.ASSESSMENT_COMPLETE
    assert "plan_id" in response.metadata
