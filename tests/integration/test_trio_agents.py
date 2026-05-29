"""
Integration tests for Trio-native agents.

Tests all 6 ported agents: Memory, Planning, Intake, Reflection, Assessment, Psychoanalyst
"""

import uuid
from datetime import datetime

import pytest
import trio

from psychoanalyst_app.agents.trio_assessment_agent import TrioAssessmentAgent
from psychoanalyst_app.agents.trio_intake_agent import TrioIntakeAgent
from psychoanalyst_app.agents.trio_memory_agent import TrioMemoryAgent
from psychoanalyst_app.agents.trio_planning_agent import TrioPlanningAgent
from psychoanalyst_app.agents.trio_psychoanalyst_agent import TrioPsychoanalystAgent
from psychoanalyst_app.agents.trio_reflection_agent import TrioReflectionAgent
from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.data_models import (
    Message,
    Session,
    Topic,
    UserProfile,
    UserStatus,
)
from psychoanalyst_app.models.structured_output_models import (
    StructuredTherapyPlanOutput,
    StructuredUserProfileOutput,
)
from psychoanalyst_app.orchestration.models import (
    ConversationContext,
    WorkflowEvent,
    WorkflowState,
)
from psychoanalyst_app.orchestration.orchestrator_helpers import (
    persist_therapy_plan_from_output,
    persist_tier3_update,
)


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
        data_of_birth=None,
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


@pytest.fixture
def style_service(service_container):
    """Provide style service for agent injections."""
    return service_container.get("style_service")


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
async def test_planning_agent_initialization(
    service_container, user_context, style_service
):
    """Test TrioPlanningAgent initialization."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    planning_agent = TrioPlanningAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )

    assert planning_agent is not None
    assert "TrioPlanningAgent" in str(planning_agent)


@pytest.mark.trio
@pytest.mark.integration
async def test_planning_agent_create_initial_plan(
    service_container, user_context, test_session, style_service
):
    """Test creating initial therapy plan."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    planning_agent = TrioPlanningAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )

    # Create initial plan output (no persistence)
    plan_output = await planning_agent.create_initial_plan(test_session, "cbt")

    assert isinstance(plan_output, StructuredTherapyPlanOutput)
    assert plan_output.selected_therapy_style == "cbt"
    assert plan_output.initial_goals


@pytest.mark.trio
@pytest.mark.integration
async def test_planning_agent_build_structured_output(
    service_container, user_context, test_session, style_service
):
    """Test that planning agent returns structured plan output."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    planning_agent = TrioPlanningAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )

    structured_plan = await planning_agent.build_structured_plan_output(
        test_session, "cbt"
    )

    assert isinstance(structured_plan, StructuredTherapyPlanOutput)
    assert structured_plan.selected_therapy_style == "cbt"


# ===== TrioIntakeAgent Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_intake_agent_initialization(service_container, user_context):
    """Test TrioIntakeAgent initialization."""
    llm_service = service_container.get("llm_service")

    intake_agent = TrioIntakeAgent(
        llm_service, user_context, config=service_container.config
    )

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
        data_of_birth=None,
        profession="",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(guest_user)

    user_context = UserContext(user_id=guest_user.user_id)
    intake_agent = TrioIntakeAgent(
        llm_service, user_context, config=service_container.config
    )

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
    assert response.workflow_event is None


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
        data_of_birth=None,
        profession="",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(guest_user)

    user_context = UserContext(user_id=guest_user.user_id)
    intake_agent = TrioIntakeAgent(
        llm_service, user_context, config=service_container.config
    )

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
    assert response.workflow_event == WorkflowEvent.START_INTAKE
    assert context.user_profile.name == "John Smith"
    structured_profile = response.metadata.get("user_profile")
    assert structured_profile is not None
    assert isinstance(structured_profile, StructuredUserProfileOutput)
    assert structured_profile.name == "John Smith"


@pytest.mark.trio
@pytest.mark.integration
async def test_intake_agent_tier1_extraction(service_container):
    """Test Tier 1 patient profile extraction from intake conversation."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")

    # Create a test user
    test_user = UserProfile(
        user_id="tier1_test_user",
        name="Sarah Johnson",
        data_of_birth=None,
        profession="",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(test_user)

    user_context = UserContext(user_id=test_user.user_id)
    intake_agent = TrioIntakeAgent(
        llm_service, user_context, config=service_container.config
    )

    # Create a rich intake conversation with patient information
    session_id = str(uuid.uuid4())
    intake_messages = [
        Message(
            role="assistant",
            content=(
                "Hello Sarah. I am Dr. AI, your therapist. "
                "What brings you here today?"
            ),
            timestamp=datetime.now(),
        ),
        Message(
            role="user",
            content=(
                "I've been feeling very anxious lately, especially at work. "
                "I'm a software engineer and the pressure has been overwhelming."
            ),
            timestamp=datetime.now(),
        ),
        Message(
            role="assistant",
            content="Tell me more about your family background.",
            timestamp=datetime.now(),
        ),
        Message(
            role="user",
            content=(
                "I grew up in a small town. My mother is supportive but my "
                "father passed away when I was 15. I have an older brother "
                "who lives abroad. The family atmosphere was generally loving "
                "but we had financial struggles."
            ),
            timestamp=datetime.now(),
        ),
        Message(
            role="assistant",
            content="What about your education and work history?",
            timestamp=datetime.now(),
        ),
        Message(
            role="user",
            content=(
                "I graduated from MIT with a computer science degree. I've "
                "been working as a software engineer for 5 years now at a "
                "tech startup. Work is both fulfilling and stressful - it's "
                "become a major part of my identity."
            ),
            timestamp=datetime.now(),
        ),
        Message(
            role="assistant",
            content="How are your current relationships?",
            timestamp=datetime.now(),
        ),
        Message(
            role="user",
            content=(
                "I'm in a long-term relationship with my partner Alex. "
                "We've been together for 3 years. I have a few close friends "
                "but I've been feeling isolated lately due to work demands."
            ),
            timestamp=datetime.now(),
        ),
    ]

    # Create session with conversation
    session = Session(
        session_id=session_id,
        user_id=test_user.user_id,
        timestamp=datetime.now(),
        transcript=intake_messages,
        topics=[],
    )
    await trio_db_service.save_session(session)

    # Create context
    context = ConversationContext(
        session_id=session_id,
        user_profile=test_user,
        therapy_plan=None,
        message_history=intake_messages,
        topics_covered=[
            "Presenting Problem",
            "Current Symptoms",
            "Family Background",
            "Work/School",
            "Relationships",
            "Personal History",
            "Goals for Therapy",
            "Mental Health History",
            "Coping Mechanisms",
            "Support System",
        ],  # Mark sufficient topics as covered
        session_start_time=datetime.now(),
        duration_minutes=60,
    )

    # Process message that triggers completion
    response = await intake_agent.process_message(
        (
            "I hope therapy can help me manage my anxiety "
            "and find better work-life balance."
        ),
        context,
    )

    # Verify intake completed
    assert response.next_action == "transition"
    assert response.workflow_event == WorkflowEvent.COMPLETE_INTAKE

    structured_profile = response.metadata.get("user_profile")
    assert structured_profile is not None
    assert isinstance(structured_profile, StructuredUserProfileOutput)
    assert structured_profile.alias == "Sarah Johnson"
    # Note: Other fields may be null if not mentioned in conversation

    # Verify timestamps are managed by persistence (not intake agent)


# ===== TrioReflectionAgent Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_reflection_agent_initialization(
    service_container, user_context, style_service
):
    """Test TrioReflectionAgent initialization."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    planning_agent = TrioPlanningAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )

    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
        config=service_container.config,
    )

    assert reflection_agent is not None
    assert "TrioReflectionAgent" in str(reflection_agent)


@pytest.mark.trio
@pytest.mark.integration
async def test_reflection_agent_create_initial_plan(
    service_container, user_context, test_session, style_service
):
    """Test reflection agent coordinating plan creation."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    planning_agent = TrioPlanningAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )

    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
        config=service_container.config,
    )

    # Create plan through reflection agent
    therapy_plan = await reflection_agent.create_initial_plan(test_session, "freud")

    assert therapy_plan is not None
    assert therapy_plan.selected_therapy_style == "freud"


@pytest.mark.trio
@pytest.mark.integration
async def test_reflection_agent_session_enrichment(
    service_container, user_context, test_session, style_service
):
    """Test reflection agent enriching session with Tier 2 psychological data."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    # Mock the structured response for Tier 2 enrichment
    # This will be called by _enrich_session()
    tier2_enrichment_data = {
        "psychological_summary": (
            "The patient presented with anxiety related to work stress. "
            "Discussion focused on coping mechanisms and underlying fears "
            "of failure. The patient demonstrated good insight and "
            "willingness to explore deeper issues."
        ),
        "dominant_affects": ["anxiety", "fear", "determination"],
        "key_themes": ["work stress", "fear of failure", "coping strategies"],
        "notable_interactions": (
            "Patient showed resistance when discussing childhood experiences, "
            "but later opened up after gentle exploration."
        ),
        "interpretations": (
            "Therapist linked current work anxiety to early experiences of "
            "parental expectations and performance pressure."
        ),
        "patient_reactions": (
            "Patient acknowledged the connection and showed visible emotional "
            "response, indicating deeper recognition of the pattern."
        ),
    }

    from unittest.mock import AsyncMock

    from psychoanalyst_app.models.structured_output_models import Tier2Enrichment

    original_structured = llm_service.generate_structured_output_async

    async def _structured_side_effect(prompt, schema, method="json_schema"):
        if schema is Tier2Enrichment:
            return Tier2Enrichment.model_validate(tier2_enrichment_data)
        return await original_structured(prompt, schema, method=method)

    llm_service.generate_structured_output_async = AsyncMock(
        side_effect=_structured_side_effect
    )

    # Verify session is not yet enriched
    assert test_session.enriched is False

    # Create agents
    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )

    planning_agent = TrioPlanningAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )

    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
        config=service_container.config,
    )

    # Generate comprehensive reflection (which triggers enrichment)
    (
        reflection,
        _profile_output,
        tier2_enrichment,
        _tier3_update,
    ) = await reflection_agent.generate_comprehensive_reflection(
        test_session, current_plan=None
    )

    # Verify reflection was generated
    assert reflection is not None
    assert reflection["session_id"] == test_session.session_id

    # Verify enrichment payload returned (persistence handled by orchestrator)
    assert tier2_enrichment is not None
    assert tier2_enrichment["psychological_summary"] == tier2_enrichment_data[
        "psychological_summary"
    ]
    assert tier2_enrichment["dominant_affects"] == tier2_enrichment_data[
        "dominant_affects"
    ]
    assert tier2_enrichment["key_themes"] == tier2_enrichment_data["key_themes"]
    assert tier2_enrichment["notable_interactions"] == tier2_enrichment_data[
        "notable_interactions"
    ]
    assert tier2_enrichment["interpretations"] == tier2_enrichment_data[
        "interpretations"
    ]
    assert tier2_enrichment["patient_reactions"] == tier2_enrichment_data[
        "patient_reactions"
    ]

    persisted_session = await trio_db_service.get_session(test_session.session_id)
    assert persisted_session is not None
    assert persisted_session.enriched is False


# ===== TrioAssessmentAgent Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_assessment_agent_initialization(
    service_container, user_context, style_service
):
    """Test TrioAssessmentAgent initialization."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    # Create a mock reflection agent
    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        None,
        None,
        config=service_container.config,
    )

    assessment_agent = TrioAssessmentAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        reflection_agent,
        style_service=style_service,
    )

    assert assessment_agent is not None


@pytest.mark.trio
@pytest.mark.integration
async def test_assessment_agent_process_assessment(
    service_container, user_context, test_session, style_service
):
    """Test conducting assessment via orchestrator interface."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    # Create a mock reflection agent
    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        None,
        None,
        config=service_container.config,
    )

    assessment_agent = TrioAssessmentAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        reflection_agent,
        style_service=style_service,
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
async def test_psychoanalyst_agent_initialization(
    service_container, user_context, style_service
):
    """Test TrioPsychoanalystAgent initialization."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    psychoanalyst_agent = TrioPsychoanalystAgent(
        llm_service,
        trio_db_service,
        rag_service,
        style_service=style_service,
        config=service_container.config,
    )

    assert psychoanalyst_agent is not None
    assert psychoanalyst_agent._get_agent_display_name() == "therapist"


# ===== Integration Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_full_agent_workflow(
    service_container, test_user, test_session, style_service
):
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
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )
    plan_output = await planning_agent.create_initial_plan(test_session, "cbt")
    assert plan_output is not None
    therapy_plan = await persist_therapy_plan_from_output(
        trio_db_service=trio_db_service,
        user_id=test_user.user_id,
        plan_output=plan_output,
    )

    # Step 3: Reflection agent coordinates
    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
        config=service_container.config,
    )
    (
        comprehensive_reflection,
        _profile_output,
        _tier2_enrichment,
        _tier3_update,
    ) = await reflection_agent.generate_comprehensive_reflection(
        test_session, therapy_plan
    )
    assert comprehensive_reflection is not None
    assert "session_context" in comprehensive_reflection

    # Step 4: Psychoanalyst agent is ready to conduct therapy
    psychoanalyst_agent = TrioPsychoanalystAgent(
        llm_service,
        trio_db_service,
        rag_service,
        style_service=style_service,
        config=service_container.config,
    )
    assert psychoanalyst_agent is not None


@pytest.mark.trio
@pytest.mark.integration
async def test_concurrent_agent_operations(
    service_container, test_user, test_session, style_service
):
    """Test concurrent operations across multiple agents."""
    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")
    user_context = UserContext(user_id=test_user.user_id)

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )
    planning_agent = TrioPlanningAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
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
    service_container, user_context, test_session, style_service
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
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )
    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
        config=service_container.config,
    )

    assessment_agent = TrioAssessmentAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        reflection_agent,
        style_service=style_service,
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
    assert response.next_action == "await_selection"
    assert response.workflow_event is None
    assert response.metadata.get("selected_style") == "cbt"


@pytest.mark.trio
@pytest.mark.integration
async def test_assessment_agent_creates_tier3_and_tier4(
    service_container, style_service
):
    """Test assessment agent creating initial Tier 3 & 4 data."""
    from psychoanalyst_app.models.data_models import UserProfile, UserStatus

    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    # Create test user with Tier 1 user profile fields
    test_user = UserProfile(
        user_id="tier34_test_user",
        name="Test Patient",
        data_of_birth=None,
        profession="Engineer",
        status=UserStatus.INTAKE_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(test_user)

    # Create Tier 1 user profile fields
    updated_profile = test_user.model_copy(
        update={
            "alias": "Test Patient",
            "gender": "Non-binary",
            "cultural_background": "Asian-American",
            "primary_language": "English",
            "parents": "Mother supportive, father distant",
            "siblings": "One younger sister",
            "family_atmosphere": "Generally warm but with occasional conflict",
            "significant_events": "Parents divorced when patient was 10",
            "education": "BS in Computer Science",
            "work_history": "Software engineer for 5 years",
            "relationship_to_work": "Source of both pride and stress",
            "relationships": "Single, few close friends",
            "social_context": "Somewhat isolated due to work demands",
            "current_situation": "High work stress, seeking better balance",
            "preferred_school": None,
            "boundary_notes": None,
            "frame_notes": None,
            "updated_at": datetime.now(),
        }
    )
    await trio_db_service.update_user_profile(
        updated_profile, change_summary="Test Tier 1 setup"
    )

    # Create intake session
    intake_session_id = str(uuid.uuid4())
    intake_session = Session(
        session_id=intake_session_id,
        user_id=test_user.user_id,
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="assistant",
                content="Tell me about what brings you here today.",
                timestamp=datetime.now(),
            ),
            Message(
                role="user",
                content=(
                    "I've been feeling overwhelmed with work stress and "
                    "I'm struggling to maintain relationships."
                ),
                timestamp=datetime.now(),
            ),
        ],
        topics=[],
    )
    await trio_db_service.save_session(intake_session)

    # Mock Tier 3 extraction response
    tier3_data = {
        "current_focus": {
            "theme": "Work-life balance and relationship strain",
            "salience": (
                "Patient presents with acute work stress that is "
                "impacting personal relationships and overall wellbeing"
            ),
        },
        "transference": {
            "idealization": None,
            "devaluation": None,
            "boundaries": None,
            "other_patterns": "Early signs of trust-building",
        },
        "narratives": [
            {
                "title": "The Overachiever",
                "description": (
                    "Patient identifies strongly with work performance "
                    "as source of self-worth"
                ),
                "first_appeared": "intake",
            }
        ],
        "defenses": {
            "primary_defenses": ["intellectualization", "isolation"],
            "defensive_style": "Cerebral, emotionally distancing",
            "flexibility": "Somewhat rigid",
        },
        "orientation": {
            "pacing": "Gradual, build trust before deep exploration",
            "risk_areas": ["perfectionism", "self-criticism"],
            "key_questions": [
                "What does work success mean to you?",
                "How do you experience emotional intimacy?",
            ],
        },
    }

    # Mock Tier 4 extraction response
    tier4_data = {
        "initial_goals": [
            "Reduce work-related stress and anxiety",
            "Improve work-life balance",
            "Develop healthier relationship patterns",
        ],
        "current_progress": (
            "Patient beginning therapy with awareness of work stress "
            "and relationship difficulties. Shows good insight and "
            "motivation for change. Currently experiencing moderate "
            "anxiety related to work performance."
        ),
        "planned_interventions": [
            "Cognitive restructuring around perfectionism",
            "Mindfulness-based stress reduction",
            "Interpersonal effectiveness skills",
        ],
        "status": "active",
    }

    from unittest.mock import AsyncMock

    from psychoanalyst_app.models.data_models import PatientAnalysis
    from psychoanalyst_app.models.structured_output_models import Tier4Extract

    original_structured = llm_service.generate_structured_output_async

    async def mock_structured_tier34(prompt, schema, method="json_schema"):
        if schema is PatientAnalysis:
            return PatientAnalysis.model_validate(tier3_data)
        if schema is Tier4Extract:
            return Tier4Extract.model_validate(tier4_data)
        return await original_structured(prompt, schema, method=method)

    llm_service.generate_structured_output_async = AsyncMock(
        side_effect=mock_structured_tier34
    )

    # Create user context and agents
    user_context = UserContext(user_id=test_user.user_id)

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )
    planning_agent = TrioPlanningAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )
    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
        config=service_container.config,
    )

    assessment_agent = TrioAssessmentAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        reflection_agent,
        style_service=style_service,
    )

    # Create context
    context = ConversationContext(
        session_id=intake_session.session_id,
        user_profile=test_user,
        therapy_plan=None,
        message_history=intake_session.transcript,
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=60,
    )

    # Process style selection (no persistence; UI handles selection)
    response = await assessment_agent.process_selection("cbt", context)

    # Verify response
    assert response is not None
    assert response.workflow_event is None
    assert response.next_action == "await_selection"
    assert response.metadata.get("selected_style") == "cbt"

    tier3_analysis = await trio_db_service.get_latest_patient_analysis(
        test_user.user_id
    )
    assert tier3_analysis is None

    tier4_plan = await trio_db_service.get_latest_therapy_plan(test_user.user_id)
    assert tier4_plan is None


@pytest.mark.trio
@pytest.mark.integration
async def test_reflection_agent_tier3_versioning(service_container, style_service):
    """Test Tier 3 versioning through reflection agent."""
    import json

    from psychoanalyst_app.models.data_models import (
        Session,
        TherapyPlan,
        UserProfile,
        UserStatus,
    )

    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    # Create test user
    test_user = UserProfile(
        user_id="tier3_versioning_test",
        name="Versioning Test Patient",
        data_of_birth=None,
        profession="Designer",
        status=UserStatus.PLAN_UPDATE_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(test_user)

    # Create Tier 1 user profile fields (required for reflection)
    updated_profile = test_user.model_copy(
        update={
            "alias": "Versioning Test Patient",
            "gender": "Female",
            "cultural_background": "European-American",
            "primary_language": "English",
            "parents": "Both parents present, mother anxious",
            "siblings": "Only child",
            "family_atmosphere": "Tense, high expectations",
            "significant_events": "Mother's anxiety was formative influence",
            "education": "MFA in Design",
            "work_history": "Freelance designer for 3 years",
            "relationship_to_work": "Creative outlet but financially unstable",
            "relationships": "In long-term relationship, some conflict",
            "social_context": "Small circle of close friends",
            "current_situation": "Career uncertainty causing anxiety",
            "preferred_school": "psychodynamic",
            "boundary_notes": None,
            "frame_notes": None,
            "updated_at": datetime.now(),
        }
    )
    await trio_db_service.update_user_profile(
        updated_profile, change_summary="Test Tier 1 setup"
    )

    # Create initial Tier 3 (version 1)
    from psychoanalyst_app.models.data_models import (
        AnalyticOrientation,
        CurrentFocus,
        DefensiveOrganization,
        PatientAnalysis,
        PatientAnalysisVersion,
        RecurringNarrative,
        TransferenceImpressions,
    )

    initial_analysis = PatientAnalysis(
        current_focus=CurrentFocus(
            theme="Career anxiety and financial insecurity",
            salience=(
                "Patient presents with acute anxiety about career "
                "stability and financial future"
            ),
        ),
        transference=TransferenceImpressions(
            idealization=None,
            devaluation=None,
            boundaries=None,
            other_patterns="Early therapeutic alliance forming",
        ),
        narratives=[
            RecurringNarrative(
                title="The Struggling Artist",
                description=(
                    "Patient identifies with creative work but struggles "
                    "with financial realities"
                ),
                first_appeared="intake",
            )
        ],
        defenses=DefensiveOrganization(
            primary_defenses=["rationalization", "intellectualization"],
            defensive_style="Cerebral, avoids emotional depth",
            flexibility="Moderately flexible",
        ),
        orientation=AnalyticOrientation(
            pacing="Build trust, explore career anxieties gradually",
            risk_areas=["perfectionism", "financial stress"],
            key_questions=[
                "What does creative success mean to you?",
                "How do you manage uncertainty?",
            ],
        ),
    )

    tier3_v1 = PatientAnalysisVersion(
        user_id=test_user.user_id,
        version=1,
        analysis_data=initial_analysis,
        created_at=datetime.now(),
        created_by_session=None,
        change_summary=None,
        superseded_by=None,
    )
    await trio_db_service.save_patient_analysis_version(tier3_v1)

    # Create therapy plan
    therapy_plan = TherapyPlan(
        plan_id=str(uuid.uuid4()),
        user_id=test_user.user_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        plan_details={"focus": "career anxiety"},
        initial_goals=[
            "Explore relationship between career anxiety and family patterns",
            "Develop tolerance for uncertainty",
        ],
        current_progress="Baseline",
        planned_interventions=["Exploratory listening"],
        status="active",
        version=1,
        selected_therapy_style="psychodynamic",
    )
    await trio_db_service.save_therapy_plan(therapy_plan)

    # Create therapy session with significant content that should trigger update
    session_id = str(uuid.uuid4())
    therapy_session = Session(
        session_id=session_id,
        user_id=test_user.user_id,
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="assistant",
                content="How have things been since our last session?",
                timestamp=datetime.now(),
            ),
            Message(
                role="user",
                content=(
                    "I had a breakthrough this week. I realized my anxiety "
                    "about money isn't really about money at all - it's about "
                    "my mother's constant worry about security. I've been "
                    "carrying her anxiety as my own. Also, I got angry at my "
                    "partner for the first time in months, which felt scary "
                    "but also liberating."
                ),
                timestamp=datetime.now(),
            ),
            Message(
                role="assistant",
                content=(
                    "That's a significant insight - recognizing the "
                    "intergenerational transmission of anxiety. And the anger "
                    "- tell me more about what made that feel liberating."
                ),
                timestamp=datetime.now(),
            ),
            Message(
                role="user",
                content=(
                    "I think I've been so afraid of conflict because I saw "
                    "how anxious my mother got. But expressing anger actually "
                    "brought my partner and me closer. It's like I'm learning "
                    "I can have feelings without everything falling apart."
                ),
                timestamp=datetime.now(),
            ),
        ],
        topics=[],
    )
    await trio_db_service.save_session(therapy_session)

    from unittest.mock import AsyncMock

    from psychoanalyst_app.models.data_models import PatientAnalysis
    from psychoanalyst_app.models.structured_output_models import ChangeDetectionDecision, Tier2Enrichment

    tier2_data = {
        "psychological_summary": (
            "Patient demonstrated significant insight this session, recognizing "
            "intergenerational transmission of anxiety from mother. Also reported "
            "breakthrough in expressing anger toward partner, strengthening relationship."
        ),
        "dominant_affects": ["anxiety", "anger", "relief"],
        "key_themes": [
            "intergenerational anxiety transmission",
            "anger expression",
            "relationship intimacy",
        ],
        "notable_interactions": (
            "Patient showed increased emotional openness and depth of self-reflection."
        ),
        "interpretations": (
            "Therapist linked patient's financial anxiety to mother's chronic worry about security."
        ),
        "patient_reactions": (
            "Patient receptive to interpretation, elaborated with new material."
        ),
    }

    updated_tier3 = {
        "current_focus": {
            "theme": "Intergenerational anxiety and emotional freedom",
            "salience": (
                "Patient has connected career anxiety to maternal influence and is exploring "
                "emotional expression as path to autonomy"
            ),
        },
        "transference": {
            "idealization": None,
            "devaluation": None,
            "boundaries": None,
            "other_patterns": (
                "Strong therapeutic alliance; patient trusts therapist enough to explore difficult material"
            ),
        },
        "narratives": [
            {
                "title": "The Struggling Artist",
                "description": (
                    "Patient identifies with creative work but struggles with financial realities. "
                    "Now recognizing this anxiety as inherited from mother."
                ),
                "first_appeared": "intake",
            },
            {
                "title": "Mother's Anxious Daughter",
                "description": (
                    "Patient carries mother's chronic anxiety about security and is beginning "
                    "to differentiate her own feelings from maternal introject."
                ),
                "first_appeared": session_id,
            },
        ],
        "defenses": {
            "primary_defenses": [
                "intellectualization",
                "identification with aggressor",
            ],
            "defensive_style": (
                "Previously cerebral; now showing greater affective range and access to anger"
            ),
            "flexibility": "Improving significantly",
        },
        "orientation": {
            "pacing": "Can move faster now; patient ready for deeper work",
            "risk_areas": [
                "fear of maternal abandonment",
                "guilt about differentiation",
            ],
            "key_questions": [
                "What would it mean to choose differently from mother?",
                "How do you distinguish your anxiety from hers?",
            ],
        },
    }

    original_structured = llm_service.generate_structured_output_async

    async def mock_structured_versioning(prompt, schema, method="json_schema"):
        if schema is Tier2Enrichment:
            return Tier2Enrichment.model_validate(tier2_data)
        if schema is ChangeDetectionDecision:
            return ChangeDetectionDecision.model_validate(
                {
                    "update_needed": True,
                    "change_summary": (
                        "Major shift in clinical understanding: intergenerational anxiety connection "
                        "and increased flexibility with anger expression"
                    ),
                    "confidence": "high",
                }
            )
        if schema is PatientAnalysis:
            return PatientAnalysis.model_validate(updated_tier3)
        return await original_structured(prompt, schema, method=method)

    llm_service.generate_structured_output_async = AsyncMock(
        side_effect=mock_structured_versioning
    )

    # Create user context and agents
    user_context = UserContext(user_id=test_user.user_id)

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )
    planning_agent = TrioPlanningAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )
    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
        config=service_container.config,
    )

    # Run reflection (should create Tier 3 v2)
    current_plan = await trio_db_service.get_latest_therapy_plan(test_user.user_id)
    (
        reflection,
        _profile_output,
        _tier2_enrichment,
        _tier3_update,
    ) = await reflection_agent.generate_comprehensive_reflection(
        therapy_session, current_plan=current_plan
    )

    # Verify reflection metadata shows Tier 3 update
    assert reflection is not None
    assert reflection["tier3_updated"] is True
    assert reflection["tier3_version"] == 2
    assert reflection["tier4_updated"] is True
    assert _tier3_update is not None
    assert await persist_tier3_update(
        trio_db_service=trio_db_service,
        user_id=test_user.user_id,
        session_id=session_id,
        tier3_update=_tier3_update,
    )

    # Verify Tier 3 v2 was created
    tier3_v2 = await trio_db_service.get_latest_patient_analysis(
        test_user.user_id
    )
    assert tier3_v2 is not None
    assert tier3_v2.version == 2
    assert tier3_v2.user_id == test_user.user_id
    assert tier3_v2.created_by_session == session_id
    assert tier3_v2.change_summary is not None
    assert "intergenerational" in tier3_v2.change_summary.lower()
    assert tier3_v2.superseded_by is None  # Latest version not superseded

    # Verify v2 content reflects session insights
    assert (
        "Intergenerational anxiety" in tier3_v2.analysis_data.current_focus.theme
    )
    assert len(tier3_v2.analysis_data.narratives) == 2  # Original + new
    assert (
        "Mother's Anxious Daughter" in
        [n.title for n in tier3_v2.analysis_data.narratives]
    )
    assert "Improving" in tier3_v2.analysis_data.defenses.flexibility

    latest_plan = await trio_db_service.get_latest_therapy_plan(test_user.user_id)
    assert latest_plan is not None

    # Verify old version was marked as superseded
    tier3_v1_updated = await trio_db_service.get_patient_analysis_version(
        test_user.user_id, version=1
    )
    assert tier3_v1_updated is not None
    assert tier3_v1_updated.superseded_by == tier3_v2.analysis_id

    # Verify we can still retrieve old version
    assert tier3_v1_updated.version == 1
    assert (
        tier3_v1_updated.analysis_data.current_focus.theme ==
        "Career anxiety and financial insecurity"
    )


@pytest.mark.trio
@pytest.mark.integration
async def test_reflection_agent_tier3_no_update_when_stable(
    service_container, style_service
):
    """Test Tier 3 not updated when session doesn't warrant change."""
    import json

    from psychoanalyst_app.models.data_models import (
        Session,
        TherapyPlan,
        UserProfile,
        UserStatus,
    )

    llm_service = service_container.get("llm_service")
    trio_db_service = service_container.get("trio_db_service")
    rag_service = service_container.get("rag_service")

    # Create test user
    test_user = UserProfile(
        user_id="tier3_stable_test",
        name="Stable Test Patient",
        data_of_birth=None,
        profession="Accountant",
        status=UserStatus.PLAN_UPDATE_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(test_user)

    # Create Tier 1 user profile fields
    updated_profile = test_user.model_copy(
        update={
            "alias": "Stable Test Patient",
            "gender": "Male",
            "cultural_background": "American",
            "primary_language": "English",
            "parents": "Both parents, stable upbringing",
            "siblings": "Two siblings",
            "family_atmosphere": "Supportive",
            "significant_events": None,
            "education": "BA in Accounting",
            "work_history": "Accountant for 10 years",
            "relationship_to_work": "Stable and satisfying",
            "relationships": "Married, supportive partner",
            "social_context": "Good social network",
            "current_situation": "General life stress, minor anxiety",
            "preferred_school": "cbt",
            "boundary_notes": None,
            "frame_notes": None,
            "updated_at": datetime.now(),
        }
    )
    await trio_db_service.update_user_profile(
        updated_profile, change_summary="Test Tier 1 setup"
    )

    # Create initial Tier 3 (version 1)
    from psychoanalyst_app.models.data_models import (
        AnalyticOrientation,
        CurrentFocus,
        DefensiveOrganization,
        PatientAnalysis,
        PatientAnalysisVersion,
        RecurringNarrative,
        TransferenceImpressions,
    )

    initial_analysis = PatientAnalysis(
        current_focus=CurrentFocus(
            theme="General life stress management",
            salience="Patient managing everyday stressors effectively",
        ),
        transference=TransferenceImpressions(
            idealization=None,
            devaluation=None,
            boundaries=None,
            other_patterns="Collaborative therapeutic relationship",
        ),
        narratives=[
            RecurringNarrative(
                title="The Stable Professional",
                description=(
                    "Patient has stable life but seeks better coping skills"
                ),
                first_appeared="intake",
            )
        ],
        defenses=DefensiveOrganization(
            primary_defenses=["suppression", "sublimation"],
            defensive_style="Healthy, adaptive",
            flexibility="Good flexibility",
        ),
        orientation=AnalyticOrientation(
            pacing="Steady progress, skill-building focus",
            risk_areas=[],
            key_questions=["What coping strategies work best for you?"],
        ),
    )

    tier3_v1 = PatientAnalysisVersion(
        user_id=test_user.user_id,
        version=1,
        analysis_data=initial_analysis,
        created_at=datetime.now(),
        created_by_session=None,
        change_summary=None,
        superseded_by=None,
    )
    await trio_db_service.save_patient_analysis_version(tier3_v1)

    # Create therapy plan
    therapy_plan = TherapyPlan(
        plan_id=str(uuid.uuid4()),
        user_id=test_user.user_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        plan_details={"focus": "stress management"},
        initial_goals=["Develop stress management skills"],
        current_progress="Baseline",
        planned_interventions=["Skills practice"],
        status="active",
        version=1,
        selected_therapy_style="cbt",
    )
    await trio_db_service.save_therapy_plan(therapy_plan)

    # Create routine therapy session (no major breakthroughs)
    session_id = str(uuid.uuid4())
    therapy_session = Session(
        session_id=session_id,
        user_id=test_user.user_id,
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="assistant",
                content="How was your week?",
                timestamp=datetime.now(),
            ),
            Message(
                role="user",
                content=(
                    "Pretty good. Work was busy but I used the breathing "
                    "techniques we discussed and they helped."
                ),
                timestamp=datetime.now(),
            ),
            Message(
                role="assistant",
                content="That's great. Tell me more about when you used them.",
                timestamp=datetime.now(),
            ),
            Message(
                role="user",
                content=(
                    "During a stressful meeting. I felt myself getting tense "
                    "and took a few deep breaths. It really helped me stay calm."
                ),
                timestamp=datetime.now(),
            ),
        ],
        topics=[],
    )
    await trio_db_service.save_session(therapy_session)

    from unittest.mock import AsyncMock

    from psychoanalyst_app.models.structured_output_models import ChangeDetectionDecision, Tier2Enrichment

    tier2_data = {
        "psychological_summary": (
            "Patient reported successful use of breathing techniques during a stressful work meeting. "
            "Progress is steady and consistent with treatment plan."
        ),
        "dominant_affects": ["calm", "satisfaction"],
        "key_themes": ["stress management", "skill application"],
        "notable_interactions": None,
        "interpretations": None,
        "patient_reactions": None,
    }

    original_structured = llm_service.generate_structured_output_async

    async def mock_structured_stable(prompt, schema, method="json_schema"):
        if schema is Tier2Enrichment:
            return Tier2Enrichment.model_validate(tier2_data)
        if schema is ChangeDetectionDecision:
            return ChangeDetectionDecision.model_validate(
                {"update_needed": False, "change_summary": None, "confidence": "high"}
            )
        return await original_structured(prompt, schema, method=method)

    llm_service.generate_structured_output_async = AsyncMock(
        side_effect=mock_structured_stable
    )

    # Create user context and agents
    user_context = UserContext(user_id=test_user.user_id)

    memory_agent = TrioMemoryAgent(
        llm_service, trio_db_service, rag_service, user_context
    )
    planning_agent = TrioPlanningAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        style_service=style_service,
    )
    reflection_agent = TrioReflectionAgent(
        llm_service,
        trio_db_service,
        rag_service,
        user_context,
        memory_agent,
        planning_agent,
        config=service_container.config,
    )

    # Run reflection (should NOT create Tier 3 v2)
    (
        reflection,
        _profile_output,
        _tier2_enrichment,
        _tier3_update,
    ) = await reflection_agent.generate_comprehensive_reflection(therapy_session)

    # Verify reflection metadata shows NO Tier 3 update
    assert reflection is not None
    assert reflection["tier3_updated"] is False
    assert reflection["tier3_version"] is None

    # Verify Tier 3 remains at v1
    tier3_current = await trio_db_service.get_latest_patient_analysis(
        test_user.user_id
    )
    assert tier3_current is not None
    assert tier3_current.version == 1  # Still version 1
    assert tier3_current.analysis_id == tier3_v1.analysis_id
    assert tier3_current.superseded_by is None  # Not superseded
