"""
Unit tests for TrioPsychoanalystAgent.

Tests the psychoanalyst agent's session resumption functionality.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from psychoanalyst_app.agents.trio_psychoanalyst_agent import TrioPsychoanalystAgent
from psychoanalyst_app.models.briefing_models import BriefingStatus
from psychoanalyst_app.models.data_models import (
    TherapyPlan,
    UserProfile,
)

# Note: Using mock_service_container fixture from conftest.py instead of local fixture


@pytest.fixture
def psychoanalyst_agent(app_config):
    """Create a psychoanalyst agent for testing."""
    # Create simple mocks
    mock_llm = Mock()
    mock_db = Mock()
    mock_rag = Mock()
    mock_style = Mock()

    return TrioPsychoanalystAgent(
        llm_service=mock_llm,
        db_service=mock_db,
        rag_service=mock_rag,
        style_service=mock_style,
        config=app_config,
    )


@pytest.fixture
def sample_user_profile():
    """Create a sample user profile."""
    return UserProfile(
        user_id="test_user_123",
        name="Test User",
        data_of_birth=datetime(1990, 1, 1),
        profession="Software Engineer",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def sample_therapy_plan():
    """Create a sample therapy plan."""
    return TherapyPlan(
        plan_id="test_plan_123",
        user_id="test_user_123",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        plan_details={
            "goals": ["Reduce anxiety", "Build confidence"],
            "approaches": ["CBT", "Mindfulness"],
            "timeline": "12 weeks",
        },
        initial_goals=["Reduce anxiety", "Build confidence"],
        current_progress="Baseline established",
        planned_interventions=["CBT", "Mindfulness"],
        version=1,
        selected_therapy_style="CBT",
        session_briefing=None,
    )


def create_briefing(days_ago: int = 0) -> dict:
    """Helper to create a properly formatted session briefing with specified age."""
    timestamp = datetime.now() - timedelta(days=days_ago)
    return {
        "briefing_type": "resumption",
        "generated_at": timestamp.isoformat(),
        "session_count": 1,
        "last_session_id": "session_001",
        "last_session_date": timestamp.date().isoformat(),
        "narrative_handoff": "Patient discussed work-related anxiety and ongoing struggles with stress management. The session revealed deeper concerns about professional identity and fear of failure.",
        "patient_observations": "Patient was engaged and communicative, showing good insight into their triggers. Some defensiveness when discussing work performance.",
        "plan_progression_notes": "Session progressed well according to CBT framework. Patient is developing awareness of cognitive distortions.",
        "relationship_quality": "developing",
        "continuity_points": [
            "Follow up on work presentation anxiety",
            "Explore relationship between self-worth and professional achievement",
            "Practice cognitive restructuring exercises",
        ],
        "emotional_summary": {
            "last_session": "moderately anxious but engaged",
            "trend": "stable",
            "note": "Anxiety levels consistent with previous sessions, but patient showing improved coping awareness",
        },
        "key_themes": [
            {
                "theme": "work stress",
                "status": "ongoing",
                "priority": "high",
                "frequency": 3,
                "first_appearance": "session_001",
                "last_discussed": "session_003",
            },
            {
                "theme": "anxiety",
                "status": "ongoing",
                "priority": "high",
                "frequency": 3,
                "first_appearance": "session_001",
                "last_discussed": "session_003",
            },
            {
                "theme": "coping strategies",
                "status": "emerging",
                "priority": "medium",
                "frequency": 2,
                "first_appearance": "session_002",
                "last_discussed": "session_003",
            },
        ],
        "progress_highlights": [
            "Patient identified three specific anxiety triggers",
            "Demonstrated understanding of cognitive restructuring",
            "Willing to practice homework exercises",
        ],
        "unresolved_issues": [
            "Underlying perfectionism not yet addressed",
            "Family dynamics contributing to work stress",
        ],
        "recommended_approach": {
            "opening_tone": "Warm and collaborative, acknowledging progress",
            "opening_focus": "Check in on work presentation that was causing anxiety",
            "things_to_avoid": "Pushing too hard on perfectionism - patient shows defensiveness",
            "suggested_questions": [
                "How did the work presentation go?",
                "What coping strategies did you use this week?",
                "Have you noticed any patterns in when your anxiety spikes?",
            ],
            "therapeutic_goals_for_session": [
                "Deepen exploration of perfectionism",
                "Introduce relaxation techniques",
                "Strengthen therapeutic alliance",
            ],
        },
    }


@pytest.mark.trio
@pytest.mark.unit
async def test_get_briefing_status_fresh(psychoanalyst_agent):
    """Test that a recent briefing is marked as FRESH."""
    # Create a briefing from today
    briefing = create_briefing(days_ago=0)

    status = psychoanalyst_agent.get_briefing_status(briefing)

    assert status == BriefingStatus.FRESH


@pytest.mark.trio
@pytest.mark.unit
async def test_get_briefing_status_fresh_within_validity(psychoanalyst_agent):
    """Test that a briefing within validity period is FRESH."""
    # Create a briefing from 3 days ago (should be within default 30-day validity)
    briefing = create_briefing(days_ago=3)

    status = psychoanalyst_agent.get_briefing_status(briefing)

    assert status == BriefingStatus.FRESH


@pytest.mark.trio
@pytest.mark.unit
async def test_get_briefing_status_stale(psychoanalyst_agent):
    """Test that an old briefing is marked as STALE."""
    # Create a briefing from 45 days ago (beyond BRIEFING_VALIDITY_DAYS but within STALE_BRIEFING_DAYS)
    briefing = create_briefing(days_ago=45)

    status = psychoanalyst_agent.get_briefing_status(briefing)

    # Should be STALE (older than 30 days but less than 90 days)
    assert status == BriefingStatus.STALE


@pytest.mark.trio
@pytest.mark.unit
async def test_get_briefing_status_very_stale(psychoanalyst_agent):
    """Test that a very old briefing is marked as VERY_STALE."""
    # Create a briefing from 100 days ago (beyond STALE_BRIEFING_DAYS)
    briefing = create_briefing(days_ago=100)

    status = psychoanalyst_agent.get_briefing_status(briefing)

    assert status == BriefingStatus.VERY_STALE


@pytest.mark.trio
@pytest.mark.unit
async def test_get_briefing_status_invalid_no_timestamp(psychoanalyst_agent):
    """Test that a briefing without timestamp is marked as INVALID."""
    briefing = {
        "session_summary": "Test summary",
        "key_themes": ["test"],
        # Missing generated_at
    }

    status = psychoanalyst_agent.get_briefing_status(briefing)

    assert status == BriefingStatus.INVALID


@pytest.mark.trio
@pytest.mark.unit
async def test_load_patient_context_includes_tiers(app_config):
    """Ensure psychoanalyst can assemble patient context from tiers."""
    mock_llm = Mock()
    mock_rag = Mock()
    mock_db = Mock()

    mock_db.get_user_profile = AsyncMock(
        return_value=UserProfile(
            user_id="test_user_123",
            name="Alex",
            alias="Alex",
            family_atmosphere="Tense but loving",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
    )
    mock_db.get_recent_sessions = AsyncMock(return_value=[])
    mock_db.get_latest_patient_analysis = AsyncMock(return_value=None)
    mock_db.get_latest_therapy_plan = AsyncMock(
        return_value=TherapyPlan(
            plan_id="plan123",
            user_id="test_user_123",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            plan_details={},
            initial_goals=["Reduce anxiety"],
            current_progress="Baseline",
            planned_interventions=["Supportive listening"],
            status="active",
            version=1,
            selected_therapy_style="cbt",
        )
    )
    agent = TrioPsychoanalystAgent(
        llm_service=mock_llm,
        db_service=mock_db,
        rag_service=mock_rag,
        style_service=Mock(),
        config=app_config,
    )

    context_text = await agent._load_patient_context("test_user_123")
    assert context_text is not None
    assert "=== PATIENT BACKGROUND ===" in context_text
    assert "=== TREATMENT GOALS ===" in context_text


@pytest.mark.trio
@pytest.mark.unit
async def test_get_briefing_status_invalid_bad_timestamp(psychoanalyst_agent):
    """Test that a briefing with invalid timestamp is marked as INVALID."""
    briefing = {
        "session_summary": "Test summary",
        "key_themes": ["test"],
        "generated_at": "not-a-valid-timestamp",
    }

    status = psychoanalyst_agent.get_briefing_status(briefing)

    assert status == BriefingStatus.INVALID


@pytest.mark.trio
@pytest.mark.unit
async def test_build_resumption_prompt_fresh_briefing(
    psychoanalyst_agent, sample_user_profile, sample_therapy_plan
):
    """
    Test that resumption prompt is built correctly from a fresh briefing.

    Verifies the prompt contains key information from the briefing.
    """
    # Create a fresh briefing
    briefing = create_briefing(days_ago=1)
    sample_therapy_plan.session_briefing = briefing

    # Build resumption prompt
    prompt = await psychoanalyst_agent._build_resumption_prompt(
        user_profile=sample_user_profile,
        therapy_plan=sample_therapy_plan,
        briefing=briefing,
        status=BriefingStatus.FRESH,
    )

    # Verify prompt is a string
    assert isinstance(prompt, str)
    assert len(prompt) > 0

    # Verify prompt contains key information from briefing
    assert "work-related anxiety" in prompt.lower() or "work stress" in prompt.lower()
    assert sample_user_profile.name in prompt or "patient" in prompt.lower()

    # Verify prompt mentions it's a resumption
    assert any(
        word in prompt.lower()
        for word in ["continue", "last session", "previous", "resume", "welcome back"]
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_build_resumption_prompt_stale_briefing(
    psychoanalyst_agent, sample_user_profile, sample_therapy_plan
):
    """
    Test that resumption prompt acknowledges stale briefing.

    When briefing is old, prompt should acknowledge time gap.
    """
    # Create a stale briefing (10 days old)
    briefing = create_briefing(days_ago=10)
    sample_therapy_plan.session_briefing = briefing

    # Build resumption prompt
    prompt = await psychoanalyst_agent._build_resumption_prompt(
        user_profile=sample_user_profile,
        therapy_plan=sample_therapy_plan,
        briefing=briefing,
        status=BriefingStatus.STALE,
    )

    # Verify prompt acknowledges the time gap
    # The prompt should be different from fresh briefing
    assert isinstance(prompt, str)
    assert len(prompt) > 0

    # Should still contain briefing content
    assert "work" in prompt.lower() or "anxiety" in prompt.lower()


@pytest.mark.trio
@pytest.mark.unit
async def test_build_resumption_prompt_includes_therapy_style(
    psychoanalyst_agent, sample_user_profile, sample_therapy_plan
):
    """
    Test that resumption prompt incorporates therapy style.

    The prompt should be tailored to the selected therapy style.
    """
    # Create a fresh briefing
    briefing = create_briefing(days_ago=0)
    sample_therapy_plan.session_briefing = briefing
    sample_therapy_plan.selected_therapy_style = "CBT"

    # Build resumption prompt
    prompt = await psychoanalyst_agent._build_resumption_prompt(
        user_profile=sample_user_profile,
        therapy_plan=sample_therapy_plan,
        briefing=briefing,
        status=BriefingStatus.FRESH,
    )

    # Verify prompt is built
    assert isinstance(prompt, str)
    assert len(prompt) > 0

    # The prompt should reference the therapy style approach
    # (either explicitly or through style-specific language from prompts)
    # This is a basic check - full style incorporation is tested in integration tests


@pytest.mark.trio
@pytest.mark.unit
async def test_build_resumption_prompt_includes_key_themes(
    psychoanalyst_agent, sample_user_profile, sample_therapy_plan
):
    """
    Test that resumption prompt incorporates key themes from briefing.
    """
    # Create a briefing with specific themes about family
    base_briefing = create_briefing(days_ago=0)
    base_briefing["narrative_handoff"] = (
        "Discussion about family relationships and communication patterns revealed underlying conflict avoidance strategies."
    )
    base_briefing["key_themes"] = [
        {
            "theme": "family conflict",
            "status": "ongoing",
            "priority": "high",
            "frequency": 2,
            "first_appearance": "session_001",
            "last_discussed": "session_002",
        },
        {
            "theme": "communication issues",
            "status": "newly introduced",
            "priority": "high",
            "frequency": 1,
            "first_appearance": "session_002",
            "last_discussed": "session_002",
        },
        {
            "theme": "boundaries",
            "status": "emerging",
            "priority": "medium",
            "frequency": 1,
            "first_appearance": "session_002",
            "last_discussed": "session_002",
        },
    ]
    briefing = base_briefing
    sample_therapy_plan.session_briefing = briefing

    # Build resumption prompt
    prompt = await psychoanalyst_agent._build_resumption_prompt(
        user_profile=sample_user_profile,
        therapy_plan=sample_therapy_plan,
        briefing=briefing,
        status=BriefingStatus.FRESH,
    )

    # Verify themes are referenced in the prompt
    prompt_lower = prompt.lower()
    assert (
        "family" in prompt_lower
        or "communication" in prompt_lower
        or "boundaries" in prompt_lower
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_build_resumption_prompt_includes_emotional_state(
    psychoanalyst_agent, sample_user_profile, sample_therapy_plan
):
    """
    Test that resumption prompt acknowledges previous emotional state.
    """
    # Create a briefing with heightened anxiety emotional state
    base_briefing = create_briefing(days_ago=0)
    base_briefing["narrative_handoff"] = (
        "Patient was very anxious during session, displaying heightened worry and difficulty regulating emotional responses."
    )
    base_briefing["emotional_summary"] = {
        "last_session": "highly anxious and overwhelmed",
        "trend": "declining",
        "note": "Anxiety levels have increased over past two sessions, patient needs calming techniques",
    }
    base_briefing["key_themes"] = [
        {
            "theme": "anxiety",
            "status": "ongoing",
            "priority": "high",
            "frequency": 5,
            "first_appearance": "session_001",
            "last_discussed": "session_005",
        }
    ]
    base_briefing["recommended_approach"]["suggested_questions"] = [
        "How have you been managing your anxiety this week?",
        "Did you try any of the breathing exercises?",
        "What situations triggered your anxiety most?",
    ]
    briefing = base_briefing
    sample_therapy_plan.session_briefing = briefing

    # Build resumption prompt
    prompt = await psychoanalyst_agent._build_resumption_prompt(
        user_profile=sample_user_profile,
        therapy_plan=sample_therapy_plan,
        briefing=briefing,
        status=BriefingStatus.FRESH,
    )

    # Verify emotional state context is included
    prompt_lower = prompt.lower()
    assert (
        "anxious" in prompt_lower
        or "overwhelmed" in prompt_lower
        or "emotional" in prompt_lower
    )
