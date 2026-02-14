"""Unit tests for TrioAssessmentAgent scoring/topic helpers."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from psychoanalyst_app.agents.trio_assessment_agent import TrioAssessmentAgent
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.data_models import Message, UserProfile, UserStatus
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


def test_resolve_recommendation_score_prefers_payload_and_clamps():
    agent = _build_agent()

    assert agent._resolve_recommendation_score({"score": 1.2}, 0) == 1.0
    assert agent._resolve_recommendation_score({"score": -1}, 0) == 0.0
    assert agent._resolve_recommendation_score({}, 0) == 0.9
    assert agent._resolve_recommendation_score({}, 1) == 0.8
    assert agent._resolve_recommendation_score({}, 2) == 0.7


def test_extract_key_topics_uses_payload_or_assessment_lines():
    agent = _build_agent()

    assert agent._extract_key_topics({"key_topics": ["anxiety", "work stress"]}) == [
        "anxiety",
        "work stress",
    ]
    assert agent._extract_key_topics({"topics": ["sleep", "avoidance"]}) == [
        "sleep",
        "avoidance",
    ]

    extracted = agent._extract_key_topics(
        {
            "assessment": "- Work conflict.\n- Avoidance patterns\n\nGeneral summary line",
        }
    )
    assert extracted == ["Work conflict", "Avoidance patterns", "General summary line"]


@pytest.mark.trio
async def test_process_assessment_assigns_rank_scores_in_metadata():
    agent = _build_agent()
    agent._generate_recommendations = AsyncMock(
        return_value=[
            {"style_id": "freud", "assessment": "Depth-oriented approach"},
            {"style_id": "jung", "assessment": "Symbolic and narrative framing"},
            {"style_id": "cbt", "assessment": "Structured skills focus"},
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
    assert scores == [0.9, 0.8, 0.7]
