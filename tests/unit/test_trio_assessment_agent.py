"""Unit tests for TrioAssessmentAgent scoring/topic helpers."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from psychoanalyst_app.agents.assessment import TrioAssessmentAgent
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.domain import Message, UserProfile, UserStatus
from psychoanalyst_app.orchestration.models import ConversationContext

pytestmark = [pytest.mark.unit]


def _build_agent() -> TrioAssessmentAgent:
    return TrioAssessmentAgent(
        llm_service=Mock(),
        db_service=Mock(),
        rag_service=Mock(),
        user_context=UserContext("user_123"),
        reflection_agent=Mock(),
        style_service=Mock(),
    )


from psychoanalyst_app.agents.assessment.recommendations import (
    extract_key_topics,
    resolve_recommendation_score,
)


def test_resolve_recommendation_score_prefers_payload_and_clamps():
    assert resolve_recommendation_score({"score": 1.2}) == 1.0
    assert resolve_recommendation_score({"score": -1}) == 0.0
    assert resolve_recommendation_score({}) == 0.5


def test_extract_key_topics_uses_payload_only():
    assert extract_key_topics({"key_topics": ["anxiety", "work stress"]}) == [
        "anxiety",
        "work stress",
    ]
    assert extract_key_topics({"topics": ["sleep", "avoidance"]}) == [
        "sleep",
        "avoidance",
    ]
    assert extract_key_topics({"assessment": "- Work conflict"}) == []


@pytest.mark.trio
async def test_process_assessment_preserves_model_scores_in_metadata():
    agent = _build_agent()
    agent._generate_recommendations = AsyncMock(
        return_value=[
            {
                "style_id": "freud",
                "assessment": "Depth-oriented approach",
                "score": 0.91,
            },
            {
                "style_id": "jung",
                "assessment": "Symbolic and narrative framing",
                "score": 0.74,
            },
            {
                "style_id": "cbt",
                "assessment": "Structured skills focus",
                "score": 0.52,
            },
        ]
    )

    context = ConversationContext(
        session_id="session_123",
        user_profile=UserProfile(
            user_id="user_123",
            name="Test User",
            status=UserStatus.PROFILE_ONLY,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        therapy_plan=None,
        message_history=[
            Message(role="user", content="I feel overwhelmed.", timestamp=datetime.now())
        ],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=45,
    )

    response = await agent.process_assessment(context)

    scores = [item["score"] for item in response.metadata["recommendations"]]
    assert scores == [0.91, 0.74, 0.52]
