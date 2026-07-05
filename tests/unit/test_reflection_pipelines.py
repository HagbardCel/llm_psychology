from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from psychoanalyst_app.agents.note_taker.session_notes import (
    generate_session_summary_payload,
    validate_session_briefing_evidence,
)
from psychoanalyst_app.agents.reflection.tier2_pipeline import (
    apply_tier2_enrichment,
    load_or_enrich_session_record,
)
from psychoanalyst_app.agents.reflection.tier3_pipeline import (
    prepare_tier3_update_payload,
)
from psychoanalyst_app.agents.reflection.tier4_pipeline import (
    apply_tier4_updates,
    generate_combined_recommendations,
)
from psychoanalyst_app.models.domain import Message, Session, TherapyPlan
from psychoanalyst_app.models.llm_outputs import SessionBriefing


def _sample_session() -> Session:
    return Session(
        session_id="session_1",
        user_id="user_1",
        timestamp=datetime.now(),
        transcript=[
            Message(role="user", content="hello", timestamp=datetime.now()),
            Message(role="assistant", content="hi", timestamp=datetime.now()),
        ],
        topics=[],
    )


def _sample_plan() -> TherapyPlan:
    return TherapyPlan(
        plan_id="plan_1",
        user_id="user_1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        version=1,
        selected_therapy_style="cbt",
        focus="anxiety",
        initial_goals=["reduce anxiety"],
        current_progress="baseline",
        planned_interventions=["supportive listening"],
        status="active",
    )


def _briefing(**updates) -> SessionBriefing:
    payload = {
        "generated_at": datetime.now().isoformat(),
        "session_count": 1,
        "last_session_id": "session_1",
        "last_session_date": datetime.now().date().isoformat(),
        "narrative_handoff": "The patient explored work stress and possible next steps. The discussion stayed exploratory and focused on current triggers.",
        "patient_observations": "The patient was engaged.",
        "plan_progression_notes": "The plan remains appropriate.",
        "relationship_quality": "developing",
        "continuity_points": ["Follow up on work stress"],
        "emotional_summary": {"last_session": "anxious", "trend": "stable", "note": "Still engaged."},
        "key_themes": [{"theme": "work stress", "status": "ongoing", "priority": "high", "frequency": 1, "first_appearance": "session_1", "last_discussed": "session_1"}],
        "progress_highlights": [],
        "unresolved_issues": ["work stress"],
        "recommended_approach": {"opening_tone": "Warm", "opening_focus": "Check in", "things_to_avoid": "Pressure", "suggested_questions": [], "therapeutic_goals_for_session": []},
        "intervention_evidence": [],
    }
    payload.update(updates)
    return SessionBriefing.model_validate(payload)


def test_briefing_allows_proposed_intervention_without_patient_reply() -> None:
    validate_session_briefing_evidence(
        _briefing(intervention_evidence=[{"intervention": "Track worry", "evidence_level": "proposed"}]),
        _sample_session(),
    )


def test_briefing_acceptance_requires_cited_patient_text() -> None:
    session = _sample_session()
    session.transcript[0].content = "Yes, I can try tracking that this week."
    validate_session_briefing_evidence(
        _briefing(intervention_evidence=[{"intervention": "Track worry", "evidence_level": "accepted", "patient_turn_index": 0, "patient_evidence": "I can try tracking that"}]),
        session,
    )
    with pytest.raises(ValueError, match="unsupported agreement"):
        validate_session_briefing_evidence(
            _briefing(narrative_handoff="The patient agreed to try tracking worry this week. This unsupported claim should be rejected before persistence."),
            _sample_session(),
        )


def test_briefing_rejects_unsupported_progress_overclaim() -> None:
    with pytest.raises(ValueError, match="unsupported agreement"):
        validate_session_briefing_evidence(
            _briefing(
                plan_progression_notes=(
                    "The session advanced the plan and the patient made progress "
                    "with the proposed mapping exercise."
                )
            ),
            _sample_session(),
        )


def test_apply_tier2_enrichment_marks_session_enriched() -> None:
    session = _sample_session()
    enriched = apply_tier2_enrichment(
        session,
        {
            "psychological_summary": "summary",
            "dominant_affects": ["anxiety"],
            "key_themes": ["work"],
            "notable_interactions": "none",
            "interpretations": "none",
            "patient_reactions": "engaged",
        },
    )

    assert enriched.enriched is True
    assert enriched.psychological_summary == "summary"
    assert enriched.key_themes == ["work"]


@pytest.mark.trio
async def test_load_or_enrich_session_record_enriches_when_missing(monkeypatch) -> None:
    session = _sample_session()
    db_service = AsyncMock()
    db_service.get_session.return_value = session

    async def _fake_enrich(*_args, **_kwargs):
        return {"psychological_summary": "tier2", "key_themes": ["theme"]}

    monkeypatch.setattr(
        "psychoanalyst_app.agents.reflection.tier2_pipeline.enrich_session_tier2",
        _fake_enrich,
    )

    loaded, payload = await load_or_enrich_session_record(
        db_service,
        MagicMock(),
        session,
    )

    assert payload is not None
    assert loaded.enriched is True
    assert loaded.psychological_summary == "tier2"


@pytest.mark.trio
async def test_load_or_enrich_session_record_reuses_persisted_enrichment(
    monkeypatch,
) -> None:
    session = _sample_session()
    enriched_session = apply_tier2_enrichment(
        session,
        {"psychological_summary": "persisted", "key_themes": ["theme"]},
    )
    db_service = AsyncMock()
    db_service.get_session.return_value = enriched_session
    enrich = AsyncMock()
    monkeypatch.setattr(
        "psychoanalyst_app.agents.reflection.tier2_pipeline.enrich_session_tier2",
        enrich,
    )

    loaded, payload = await load_or_enrich_session_record(
        db_service,
        MagicMock(),
        session,
    )

    assert loaded is enriched_session
    assert payload is None
    enrich.assert_not_awaited()


@pytest.mark.trio
async def test_prepare_tier3_update_payload_handles_missing_current_analysis() -> None:
    db_service = AsyncMock()
    db_service.get_latest_patient_analysis.return_value = None

    result = await prepare_tier3_update_payload(
        db_service,
        MagicMock(),
        "user_1",
        _sample_session(),
    )

    assert result == (False, None, None, None)


@pytest.mark.trio
async def test_prepare_tier3_update_payload_builds_update_when_needed(
    monkeypatch,
) -> None:
    current_tier3 = SimpleNamespace(
        version=2,
        analysis_id="analysis_1",
        user_id="user_1",
    )
    db_service = AsyncMock()
    db_service.get_latest_patient_analysis.return_value = current_tier3

    async def _fake_eval(*_args, **_kwargs):
        return (True, "new clinical signal")

    async def _fake_generate(*_args, **_kwargs):
        return {"new": "analysis"}

    monkeypatch.setattr(
        "psychoanalyst_app.agents.reflection.tier3_pipeline.evaluate_tier3_update_necessity",
        _fake_eval,
    )
    monkeypatch.setattr(
        "psychoanalyst_app.agents.reflection.tier3_pipeline.generate_updated_tier3_analysis",
        _fake_generate,
    )

    updated, version, payload, summary = await prepare_tier3_update_payload(
        db_service,
        MagicMock(),
        "user_1",
        _sample_session(),
    )

    assert updated is True
    assert version == 3
    assert summary == "new clinical signal"
    assert payload is not None
    assert payload["supersede_analysis_id"] == "analysis_1"


@pytest.mark.trio
async def test_generate_combined_recommendations_merges_sources() -> None:
    planning_agent = AsyncMock()
    planning_agent.recommend_plan_adjustments.return_value = [
        {"description": "adjust pacing", "priority": "high"}
    ]

    memory = SimpleNamespace(relationship_quality="strong")
    patterns = {"emotional_patterns": {"recent_trend": "improving"}}

    recommendations = await generate_combined_recommendations(
        planning_agent,
        memory,
        patterns,
        _sample_plan(),
    )

    sources = {rec["source"] for rec in recommendations}
    assert "memory_analysis" in sources
    assert "pattern_analysis" in sources
    assert "planning_analysis" in sources


@pytest.mark.trio
async def test_apply_tier4_updates_updates_plan_state() -> None:
    plan = _sample_plan()
    db_service = AsyncMock()
    db_service.get_session_count.return_value = 5
    session_context = SimpleNamespace(progress_indicators=["insight"])

    updated = await apply_tier4_updates(
        db_service,
        planning_agent=MagicMock(),
        user_id="user_1",
        current_plan=plan,
        session_context=session_context,
        plan_assessment={"strengths": ["engagement"]},
        plan_recommendations=[],
        session_summary="stable progress",
        tier3_updated=False,
    )

    assert updated is True
    assert "Progress indicators" in plan.current_progress


@pytest.mark.trio
async def test_apply_tier4_updates_keeps_recommendations_separate_from_interventions() -> None:
    plan = _sample_plan()
    db_service = AsyncMock()
    db_service.get_session_count.return_value = 5
    updated = await apply_tier4_updates(
        db_service,
        planning_agent=MagicMock(),
        user_id="user_1",
        current_plan=plan,
        session_context=SimpleNamespace(progress_indicators=[]),
        plan_assessment=None,
        plan_recommendations=[{"description": "Consider a sleep log", "priority": "high"}],
        session_summary="stable",
        tier3_updated=False,
    )

    assert updated is True
    assert plan.revision_recommendations == ["Consider a sleep log"]
    assert plan.planned_interventions == ["supportive listening"]


@pytest.mark.trio
async def test_generate_session_summary_payload_uses_helper(monkeypatch) -> None:
    async def _fake_summary(_llm, _session):
        return "summary text"

    monkeypatch.setattr(
        "psychoanalyst_app.agents.note_taker.session_notes.generate_session_summary",
        _fake_summary,
    )

    payload = await generate_session_summary_payload(MagicMock(), _sample_session())

    assert payload["summary"] == "summary text"
    assert payload["session_id"] == "session_1"
    assert "timestamp" in payload
