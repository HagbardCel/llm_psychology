"""Unit tests for shared context projection packing."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.models import Plan
from jung.phases.context_projection import (
    ProjectionBudgetError,
    enrich_plan_projection,
    minimal_plan_projection,
    pack_transcript_turns,
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
