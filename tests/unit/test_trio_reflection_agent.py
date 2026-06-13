"""
Unit tests for TrioReflectionAgent.

Tests the reflection agent's session briefing generation and error handling.
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from psychoanalyst_app.agents.reflection import TrioReflectionAgent
from psychoanalyst_app.agents.reflection.session_summary import (
    generate_session_briefing,
)
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.domain import (
    Message,
    Session,
    TherapyPlan,
    Topic,
    UserProfile,
)
from psychoanalyst_app.orchestration.models import (
    ConversationContext,
    WorkflowEvent,
)

# Note: Using mock_service_container fixture from conftest.py instead of local fixture


@pytest.fixture
def user_context():
    """Create a test user context."""
    return UserContext(user_id="test_user_123")


@pytest.fixture
def sample_session():
    """Create a sample therapy session for testing."""
    return Session(
        session_id="test_session_123",
        user_id="test_user_123",
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="user",
                content="I've been struggling with anxiety at work.",
                timestamp=datetime.now(),
            ),
            Message(
                role="assistant",
                content=(
                    "I understand that work-related anxiety can be "
                    "challenging. Can you tell me more about what triggers it?"
                ),
                timestamp=datetime.now(),
            ),
            Message(
                role="user",
                content=(
                    "It happens mostly during team meetings. I worry about "
                    "being judged."
                ),
                timestamp=datetime.now(),
            ),
            Message(
                role="assistant",
                content=(
                    "That's a common concern. Let's explore some coping strategies."
                ),
                timestamp=datetime.now(),
            ),
        ],
        topics=[
            Topic(name="anxiety", status="covered"),
            Topic(name="work stress", status="partially_covered"),
            Topic(name="social anxiety", status="pending"),
        ],
    )


@pytest.fixture
def sample_therapy_plan():
    """Create a sample therapy plan for testing."""
    return TherapyPlan(
        plan_id="test_plan_123",
        user_id="test_user_123",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        focus="Anxiety management",
        themes=["anxiety", "sleep"],
        timeline="12 weeks",
        initial_goals=["Reduce anxiety", "Improve sleep"],
        current_progress="Baseline established",
        planned_interventions=["CBT", "Mindfulness"],
        version=1,
        selected_therapy_style="CBT",
        session_briefing=None,
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_generate_session_briefing_structure(
    mock_service_container, user_context
):
    """
    Test that session briefing is generated with correct structure.

    Verifies that the briefing contains all required fields.
    """
    # Get services from container
    llm_service = mock_service_container.get("llm_service")
    db_service = mock_service_container.get("trio_db_service")
    rag_service = mock_service_container.get("rag_service")

    # Create mock agents
    planning_agent = Mock()
    memory_agent = Mock()

    # Create reflection agent
    agent = TrioReflectionAgent(
        llm_service=llm_service,
        db_service=db_service,
        rag_service=rag_service,
        user_context=user_context,
        planning_agent=planning_agent,
        memory_agent=memory_agent,
        config=mock_service_container.config,
    )

    # Create test data
    session_context = {
        "key_themes": ["work anxiety", "social fear"],
        "emotional_state": "anxious but engaged",
        "progress_indicators": ["awareness", "willingness"],
    }

    therapeutic_memory = {
        "significant_moments": ["Patient recognized anxiety trigger"],
        "recurring_patterns": ["Avoidance of team meetings"],
    }

    plan_assessment = {
        "goal_progress": "Early stages",
        "approach_effectiveness": "CBT techniques showing promise",
    }

    sample_session = Session(
        session_id="test_session",
        user_id="test_user_123",
        timestamp=datetime.now(),
        transcript=[Message(role="user", content="Test", timestamp=datetime.now())],
        topics=[Topic(name="test", status="pending")],
    )

    sample_plan = TherapyPlan(
        plan_id="test_plan",
        user_id="test_user_123",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        focus="test",
        initial_goals=["test"],
        current_progress="Baseline established",
        planned_interventions=["Supportive listening"],
        version=1,
        selected_therapy_style="CBT",
        session_briefing=None,
    )

    # Generate briefing
    briefing = await generate_session_briefing(
        agent.llm_service,
        agent.config,
        session_context,
        therapeutic_memory,
        plan_assessment,
        sample_session,
        sample_plan,
    )

    # Verify briefing structure
    assert briefing is not None, "Briefing should not be None"
    assert isinstance(briefing, dict), "Briefing should be a dictionary"

    # Verify required fields match SessionBriefing model
    assert "narrative_handoff" in briefing, "Briefing should have narrative_handoff"
    assert "key_themes" in briefing, "Briefing should have key_themes"
    assert "emotional_summary" in briefing, "Briefing should have emotional_summary"
    assert "generated_at" in briefing, "Briefing should have generated_at timestamp"
    assert "session_count" in briefing, "Briefing should have session_count"
    assert "last_session_id" in briefing, "Briefing should have last_session_id"

    # Verify data types
    assert isinstance(briefing["narrative_handoff"], str)
    assert isinstance(briefing["key_themes"], list)
    assert isinstance(briefing["emotional_summary"], dict)
    assert isinstance(briefing["generated_at"], str)
    assert isinstance(briefing["session_count"], int)

    # Verify timestamp is valid ISO format
    datetime.fromisoformat(briefing["generated_at"])


@pytest.mark.trio
@pytest.mark.unit
async def test_briefing_generation_failure_propagates(
    mock_service_container, user_context, sample_session
):
    """
    Test that briefing generation failures propagate correctly (fail-fast).

    This verifies the fix for the error swallowing bug.
    """
    # Get services from container
    db_service = mock_service_container.get("trio_db_service")
    rag_service = mock_service_container.get("rag_service")

    # Create therapy plan
    therapy_plan = TherapyPlan(
        plan_id="test_plan",
        user_id="test_user_123",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        focus="test",
        initial_goals=["test"],
        current_progress="Baseline established",
        planned_interventions=["Supportive listening"],
        version=1,
        selected_therapy_style="CBT",
        session_briefing=None,
    )
    await db_service.save_therapy_plan(therapy_plan)

    # Create mock agents
    planning_agent = Mock()
    planning_agent.update_plan = AsyncMock(return_value=therapy_plan)
    planning_agent.assess_plan_effectiveness = AsyncMock(return_value={})
    planning_agent.recommend_plan_adjustments = AsyncMock(return_value={})

    memory_agent = Mock()
    mock_session_context = Mock()
    mock_session_context.key_themes = ["mock_theme_1", "mock_theme_2"]
    mock_session_context.emotional_state = "neutral"
    mock_session_context.insights = []
    mock_session_context.progress_indicators = []
    memory_agent.analyze_session_context = AsyncMock(return_value=mock_session_context)

    # Create proper therapeutic memory mock
    mock_memory = Mock()
    mock_memory.session_contexts = []
    mock_memory.relationship_quality = "good"
    mock_memory.recurring_themes = {}
    mock_memory.emotional_patterns = []
    memory_agent.get_therapeutic_memory = AsyncMock(return_value=mock_memory)

    memory_agent.identify_patterns = AsyncMock(return_value={})
    memory_agent.get_continuity_context = AsyncMock(return_value={})

    # Create conversation context
    context = ConversationContext(
        session_id="test_session",
        user_profile=UserProfile(
            user_id="test_user_123",
            name="Test User",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        therapy_plan=therapy_plan,
        message_history=[],
        topics_covered=[],  # Added for test
        session_start_time=datetime.now(),  # Added for test
        duration_minutes=60,  # Added for test
    )

    # Create a mock LLM service that will raise an exception
    mock_llm = Mock()
    mock_llm.generate_response = Mock(side_effect=Exception("LLM service failure"))
    async def _fail_structured_output_async(*args, **kwargs):
        raise Exception("LLM service failure")

    mock_llm.generate_structured_output_async = _fail_structured_output_async

    # Create reflection agent with failing LLM
    agent = TrioReflectionAgent(
        llm_service=mock_llm,
        db_service=db_service,
        rag_service=rag_service,
        user_context=user_context,
        planning_agent=planning_agent,
        memory_agent=memory_agent,
        config=mock_service_container.config,
    )

    # The process_reflection should raise the exception, not swallow it
    # This is the critical test for fail-fast behavior
    with pytest.raises(Exception) as exc_info:
        await agent.process_reflection(sample_session, context)

    # Verify the exception propagated
    assert "LLM service failure" in str(exc_info.value) or "Failed" in str(
        exc_info.value
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_process_reflection_updates_plan_with_briefing(
    mock_service_container, user_context, sample_session, sample_therapy_plan
):
    """
    Test that process_reflection successfully updates therapy plan with briefing.

    This is an integration test of the full reflection workflow.
    """
    # Get services
    llm_service = mock_service_container.get("llm_service")
    db_service = mock_service_container.get("trio_db_service")
    rag_service = mock_service_container.get("rag_service")

    # Create mock agents with proper async methods
    planning_agent = Mock()
    planning_agent.update_plan = AsyncMock(return_value=sample_therapy_plan)
    planning_agent.assess_plan_effectiveness = AsyncMock(return_value={})
    planning_agent.recommend_plan_adjustments = AsyncMock(return_value=[])

    memory_agent = Mock()
    mock_session_context = Mock()
    mock_session_context.key_themes = ["test_theme_1", "test_theme_2"]
    mock_session_context.emotional_state = "positive"
    mock_session_context.insights = ["test insight"]
    mock_session_context.progress_indicators = ["improvement noted"]
    memory_agent.analyze_session_context = AsyncMock(return_value=mock_session_context)

    # Create proper therapeutic memory mock
    mock_memory = Mock()
    mock_memory.session_contexts = []
    mock_memory.relationship_quality = "good"
    mock_memory.recurring_themes = {"anxiety": 3}
    mock_memory.emotional_patterns = ["calm", "focused"]
    memory_agent.get_therapeutic_memory = AsyncMock(return_value=mock_memory)

    memory_agent.identify_patterns = AsyncMock(
        return_value={"patterns": ["test_pattern"]}
    )
    memory_agent.get_continuity_context = AsyncMock(
        return_value={"context": "test_context"}
    )

    # Save initial plan
    await db_service.save_therapy_plan(sample_therapy_plan)

    # Create user profile
    user_profile = UserProfile(
        user_id="test_user_123",
        name="Test User",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await db_service.save_user_profile(user_profile)

    # Save session
    await db_service.save_session(sample_session)

    # Create reflection agent
    agent = TrioReflectionAgent(
        llm_service=llm_service,
        db_service=db_service,
        rag_service=rag_service,
        user_context=user_context,
        planning_agent=planning_agent,
        memory_agent=memory_agent,
        config=mock_service_container.config,
    )

    # Create conversation context
    context = ConversationContext(
        session_id=sample_session.session_id,
        user_profile=user_profile,
        therapy_plan=sample_therapy_plan,
        message_history=[],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=60,
    )

    # Process reflection
    response = await agent.process_reflection(sample_session, context)

    # Verify response
    assert response is not None
    assert response.next_state is None
    assert response.workflow_event == WorkflowEvent.COMPLETE_REFLECTION
    assert "has_briefing" in response.metadata
    assert response.metadata["has_briefing"] is True
    assert response.metadata["plan_revision_required"] is False
    assert response.metadata["session_briefing_generated"] is True
    assert response.metadata["plan_id"] == sample_therapy_plan.plan_id
    assert response.metadata["plan_version"] == sample_therapy_plan.version
    assert response.metadata["session_briefing"] is not None
    assert "narrative_handoff" in response.metadata["session_briefing"]

    assert "patient_observations" in response.metadata["session_briefing"]
    assert "briefing_type" in response.metadata["session_briefing"]
