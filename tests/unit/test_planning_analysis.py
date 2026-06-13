from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from psychoanalyst_app.agents.planning.analysis import (
    assess_update_necessity,
    recommend_goal_adjustments,
    recommend_theme_adjustments,
)
from psychoanalyst_app.models.domain import Message, Session, TherapyPlan


def _plan() -> TherapyPlan:
    return TherapyPlan(
        plan_id="plan_1",
        user_id="user_1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        version=1,
        selected_therapy_style="cbt",
        focus="Work-related anxiety and sleep disruption",
        themes=["work-related anxiety", "sleep disruption"],
        timeline="12 weeks",
        initial_goals=["Reduce deadline anxiety", "Improve sleep"],
        current_progress="Baseline established",
        planned_interventions=["CBT worry mapping", "Sleep hygiene"],
        status="active",
    )


def _session(*patient_messages: str) -> Session:
    transcript = [
        Message(role="user", content=message, timestamp=datetime.now())
        for message in patient_messages
    ]
    return Session(
        session_id="session_1",
        user_id="user_1",
        timestamp=datetime.now(),
        transcript=transcript,
        topics=[],
    )


def _context(**updates):
    payload = {
        "insights": ["insight 1", "insight 2"],
        "key_themes": ["panic", "meeting anxiety"],
        "progress_indicators": ["engaged", "reflective"],
        "risk_indicators": [],
    }
    payload.update(updates)
    return SimpleNamespace(**payload)


def test_short_session_without_material_signal_does_not_require_plan_revision() -> None:
    assert (
        assess_update_necessity(
            _context(),
            SimpleNamespace(session_contexts=[]),
            _plan(),
            session=_session("I had panic before a meeting and slept badly."),
        )
        is False
    )


def test_short_session_with_material_signal_can_require_plan_revision() -> None:
    assert (
        assess_update_necessity(
            _context(risk_indicators=["safety concern"]),
            SimpleNamespace(session_contexts=[]),
            _plan(),
            session=_session("I felt unsafe yesterday."),
        )
        is True
    )


def test_theme_recommendations_ignore_normalized_duplicates() -> None:
    recommendations = recommend_theme_adjustments(
        _plan(),
        {
            "theme_patterns": {
                "dominant_themes": ["insomnia", "performance pressure"]
            }
        },
    )

    assert recommendations == []


def test_goal_progression_not_recommended_when_emotional_trend_declines() -> None:
    assert (
        recommend_goal_adjustments(
            _plan(),
            {"effectiveness_score": 0.8, "emotional_trend": "declining"},
        )
        == []
    )
