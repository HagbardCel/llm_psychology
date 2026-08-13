"""Unit tests for shared context projection packing."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.models import Plan
from jung.domain.session_artifacts import (
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
)
from jung.phases.context_projection import (
    ProjectionBudgetError,
    _iter_rich_plan_candidates,
    enrich_plan_projection,
    enrich_session_briefing_projection,
    minimal_plan_projection,
    minimal_session_briefing_projection,
    pack_prior_session_reviews,
    pack_transcript_turns,
    project_prior_session_review,
)
from jung.phases.transcript import TranscriptTurn

_PLAN_KEYS = {
    "focus",
    "themes",
    "goals",
    "current_progress",
    "planned_interventions",
    "revision_recommendations",
}


def _plan(**overrides: object) -> Plan:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "id": uuid4(),
        "version": 1,
        "selected_style": "cbt",
        "focus": "anxiety",
        "themes": ["worry", "sleep"],
        "goals": ["sleep better", "reduce worry"],
        "current_progress": "baseline progress note",
        "planned_interventions": ["grounding", "thought record"],
        "revision_recommendations": ["review goals"],
        "created_at": now,
    }
    values.update(overrides)
    return Plan(**values)  # type: ignore[arg-type]


def _turn(sequence: int, role: str, content: str) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=uuid4(),
        sequence=sequence,
        role=role,  # type: ignore[arg-type]
        content=content,
    )


def test_minimal_and_enriched_plan_preserve_canonical_keys() -> None:
    plan = _plan()
    minimal = minimal_plan_projection(plan)
    assert set(minimal) == _PLAN_KEYS
    assert minimal["themes"] == []
    assert minimal["revision_recommendations"] == []
    assert len(minimal["goals"]) == 1
    assert len(minimal["planned_interventions"]) == 1

    enriched = enrich_plan_projection(
        plan,
        baseline=minimal,
        fits=lambda _doc: True,
    )
    assert set(enriched) == _PLAN_KEYS
    assert enriched["themes"] == ["worry", "sleep"]
    assert enriched["revision_recommendations"] == ["review goals"]


def test_rich_plan_candidates_are_lazy_and_bounded() -> None:
    plan = _plan()
    candidates = _iter_rich_plan_candidates(plan)
    assert iter(candidates) is candidates
    materialized = list(candidates)
    assert len(materialized) <= 48
    assert all(
        previous != current
        for previous, current in zip(materialized, materialized[1:], strict=False)
    )
    first = materialized[0]
    assert first["focus"] == plan.focus
    assert first["current_progress"] == plan.current_progress
    assert first["themes"] == list(plan.themes)
    assert first["goals"] == list(plan.goals)
    assert first["planned_interventions"] == list(plan.planned_interventions)
    assert first["revision_recommendations"] == list(plan.revision_recommendations)


def test_enrich_plan_requires_fitting_baseline() -> None:
    plan = _plan()
    minimal = minimal_plan_projection(plan)
    with pytest.raises(ValueError, match="baseline must already fit"):
        enrich_plan_projection(plan, baseline=minimal, fits=lambda _doc: False)


def test_pack_transcript_rejects_non_increasing_sequences() -> None:
    turns = (
        _turn(1, "assistant", "a"),
        _turn(1, "user", "b"),
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        pack_transcript_turns(turns, fits=lambda _doc: True)


def test_two_role_nucleus_prefers_feasible_pair_over_same_role_greed() -> None:
    turns = (
        _turn(1, "assistant", "moderately long assistant reply " * 8),
        _turn(2, "user", "short one"),
        _turn(3, "user", "short two"),
    )

    def fits(document: dict[str, object]) -> bool:
        selected = document["transcript"]
        assert isinstance(selected, list)
        roles = {item["role"] for item in selected}
        if len(selected) >= 3:
            return False
        if roles == {"user"} and len(selected) == 2:
            return True
        if "user" in roles and "assistant" in roles and len(selected) <= 2:
            return True
        if len(selected) <= 1:
            return True
        return False

    packed = pack_transcript_turns(turns, fits=fits, require_two_roles=True)
    roles = {item["role"] for item in packed.document["transcript"]}  # type: ignore[union-attr]
    sequences = [item["sequence"] for item in packed.document["transcript"]]  # type: ignore[union-attr]
    assert roles == {"user", "assistant"}
    assert sequences == sorted(sequences)
    assert 1 in sequences
    assert len(sequences) == 2


def test_oversized_turn_is_skipped_without_blocking_older() -> None:
    turns = (
        _turn(1, "user", "tiny"),
        _turn(2, "assistant", "x" * 200),
        _turn(3, "user", "also-tiny"),
    )

    def fits(document: dict[str, object]) -> bool:
        selected = document["transcript"]
        assert isinstance(selected, list)
        total = sum(len(item["content"]) for item in selected)  # type: ignore[index]
        return total <= 40

    packed = pack_transcript_turns(turns, fits=fits, require_two_roles=False)
    contents = [item["content"] for item in packed.document["transcript"]]  # type: ignore[union-attr]
    assert contents == ["tiny", "also-tiny"]
    assert packed.omitted == 1


def test_omitted_base_is_included_in_omission_count() -> None:
    turns = (_turn(10, "user", "a"), _turn(11, "assistant", "b"))
    packed = pack_transcript_turns(
        turns,
        fits=lambda _doc: True,
        omitted_base=14,
    )
    assert packed.document["transcript_turns_omitted"] == 14
    assert packed.omitted == 14


def test_negative_omitted_base_rejected() -> None:
    with pytest.raises(ValueError, match="omitted_base"):
        pack_transcript_turns(
            (_turn(1, "user", "a"),),
            fits=lambda _doc: True,
            omitted_base=-1,
        )


def test_empty_projection_budget_error_is_typed() -> None:
    with pytest.raises(ProjectionBudgetError, match="empty transcript projection"):
        pack_transcript_turns(
            (_turn(1, "user", "a"),),
            fits=lambda _doc: False,
        )


_BRIEFING_KEYS = {
    "narrative_handoff",
    "continuity_points",
    "unresolved_issues",
    "recommended_opening_focus",
    "things_to_avoid",
    "emotional_context",
}


def _briefing(**overrides: object) -> SessionBriefing:
    values: dict[str, object] = {
        "narrative_handoff": "Session focused on readiness.",
        "recommended_opening_focus": "pace",
        "continuity_points": ("continue sleep work",),
        "unresolved_issues": ("family disclosure",),
        "things_to_avoid": ("pushing too fast",),
        "emotional_context": ("tired but engaged",),
    }
    values.update(overrides)
    return SessionBriefing(**values)  # type: ignore[arg-type]


def _review(summary: str) -> SessionReview:
    return SessionReview(
        analysis=SessionAnalysis(summary=summary, key_themes=(summary,)),
        briefing=_briefing(),
        plan_recommendation=PlanPatch(),
    )


def test_minimal_session_briefing_projection_returns_empty_lists() -> None:
    minimal = minimal_session_briefing_projection(_briefing())
    assert set(minimal) == _BRIEFING_KEYS
    assert minimal["continuity_points"] == []
    assert minimal["unresolved_issues"] == []
    assert minimal["things_to_avoid"] == []
    assert minimal["emotional_context"] == []


def test_enrich_session_briefing_requires_fitting_baseline() -> None:
    briefing = _briefing()
    minimal = minimal_session_briefing_projection(briefing)
    with pytest.raises(ValueError, match="baseline must already fit"):
        enrich_session_briefing_projection(
            briefing,
            baseline=minimal,
            fits=lambda _doc: False,
        )


def test_enrich_session_briefing_restores_lists() -> None:
    briefing = _briefing()
    minimal = minimal_session_briefing_projection(briefing)
    enriched = enrich_session_briefing_projection(
        briefing,
        baseline=minimal,
        fits=lambda _doc: True,
    )
    assert enriched["continuity_points"] == ["continue sleep work"]
    assert enriched["unresolved_issues"] == ["family disclosure"]


def test_project_prior_session_review_caps_list_items() -> None:
    projection = project_prior_session_review(
        SessionAnalysis(
            summary="Prior summary.",
            key_themes=tuple(f"theme-{index}" for index in range(100)),
            progress_indicators=tuple(f"progress-{index}" for index in range(100)),
            unresolved_topics=tuple(f"topic-{index}" for index in range(100)),
            safety_or_boundary_notes=tuple(f"safety-{index}" for index in range(100)),
            intervention_citations=(),
            patient_turn_citations=(),
        )
    )
    assert len(projection["key_themes"]) <= 6
    assert len(projection["progress_indicators"]) <= 6
    assert len(projection["unresolved_topics"]) <= 6
    assert len(projection["safety_or_boundary_notes"]) <= 6


def test_project_prior_session_review_exposes_only_approved_fields() -> None:
    projection = project_prior_session_review(
        SessionAnalysis(
            summary="Prior summary.",
            key_themes=("sleep",),
            progress_indicators=("better nights",),
            unresolved_topics=("family",),
            safety_or_boundary_notes=("none",),
            intervention_citations=(),
            patient_turn_citations=(),
        )
    )
    assert set(projection) == {
        "summary",
        "key_themes",
        "progress_indicators",
        "unresolved_topics",
        "safety_or_boundary_notes",
    }
    assert "intervention_citations" not in projection
    assert "patient_turn_citations" not in projection


def test_pack_prior_session_reviews_returns_none_when_empty_projection_unfit() -> None:
    reviews = (_review("one"), _review("two"))
    assert pack_prior_session_reviews(reviews, fits=lambda _doc: False) is None


def test_pack_prior_session_reviews_empty_list_when_channel_fits_but_no_review() -> (
    None
):
    reviews = (_review("one"), _review("two"))
    packed = pack_prior_session_reviews(
        reviews,
        fits=lambda document: len(document["prior_supervisor_reviews"]) <= 0,  # type: ignore[arg-type]
    )
    assert packed is not None
    assert packed.document["prior_supervisor_reviews"] == []
    assert packed.document["prior_supervisor_reviews_omitted"] == 2


def test_pack_prior_session_reviews_prefers_newest_and_emits_chronological() -> None:
    reviews = (_review("old"), _review("middle"), _review("newest"))
    packed = pack_prior_session_reviews(
        reviews,
        fits=lambda document: len(document["prior_supervisor_reviews"]) <= 2,  # type: ignore[arg-type]
    )
    assert packed is not None
    summaries = [
        item["summary"]
        for item in packed.document["prior_supervisor_reviews"]  # type: ignore[union-attr]
    ]
    assert summaries == ["middle", "newest"]
    assert packed.document["prior_supervisor_reviews_omitted"] == 1
