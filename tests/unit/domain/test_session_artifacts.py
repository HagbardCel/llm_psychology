"""Tests for durable session briefing and intervention evidence artifacts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jung.domain.session_artifacts import InterventionEvidence, SessionBriefing


def _evidence(
    *,
    therapist_sequence: int = 2,
    patient_sequence: int | None = 3,
    therapist_content: str = "What feels unclear?",
    patient_content: str | None = "I am not ready to do that.",
) -> InterventionEvidence:
    kwargs: dict[str, object] = {
        "intervention_description": "Exploratory questioning",
        "therapist_sequence": therapist_sequence,
        "therapist_content": therapist_content,
    }
    if patient_sequence is not None:
        kwargs["patient_sequence"] = patient_sequence
        kwargs["patient_content"] = patient_content
    return InterventionEvidence(**kwargs)  # type: ignore[arg-type]


def _briefing(
    evidence: tuple[InterventionEvidence, ...] = (),
) -> SessionBriefing:
    return SessionBriefing(
        narrative_handoff="Continue with sleep and readiness.",
        recommended_opening_focus="Ask about readiness.",
        intervention_evidence=evidence,
    )


def test_session_briefing_round_trips_through_json_dump() -> None:
    briefing = _briefing(
        (_evidence(), _evidence(therapist_sequence=4, patient_sequence=5))
    )
    restored = SessionBriefing.model_validate(briefing.model_dump(mode="json"))
    assert restored == briefing
    assert restored.intervention_evidence[0].status == "response_cited"


def test_status_derived_for_delivered_and_response_cited() -> None:
    delivered = _evidence(patient_sequence=None, patient_content=None)
    cited = _evidence()
    assert delivered.status == "delivered"
    assert cited.status == "response_cited"
    assert delivered.model_dump(mode="json")["status"] == "delivered"
    assert cited.model_dump(mode="json")["status"] == "response_cited"


def test_conflicting_stored_status_rejected() -> None:
    with pytest.raises(ValidationError, match="status conflicts"):
        InterventionEvidence.model_validate(
            {
                "intervention_description": "label",
                "therapist_sequence": 1,
                "therapist_content": "ok",
                "patient_sequence": 2,
                "patient_content": "response",
                "status": "delivered",
            }
        )


def test_explicit_null_status_rejected_as_conflict() -> None:
    with pytest.raises(ValidationError, match="status conflicts"):
        InterventionEvidence.model_validate(
            {
                "intervention_description": "label",
                "therapist_sequence": 1,
                "therapist_content": "ok",
                "patient_sequence": 3,
                "patient_content": "response",
                "status": None,
            }
        )


def test_status_present_in_validation_schema() -> None:
    schema = InterventionEvidence.model_json_schema(mode="validation")
    assert "status" in schema.get("properties", {})


def test_duplicate_therapist_sequence_rejected() -> None:
    with pytest.raises(
        ValidationError, match="therapist_sequence values must be unique"
    ):
        _briefing(
            (
                _evidence(therapist_sequence=2, patient_sequence=3),
                _evidence(therapist_sequence=2, patient_sequence=4),
            )
        )


def test_noncanonical_evidence_ordering_rejected() -> None:
    later = _evidence(therapist_sequence=4, patient_sequence=5)
    earlier = _evidence(therapist_sequence=2, patient_sequence=3)
    with pytest.raises(ValidationError, match="canonical order"):
        SessionBriefing(
            narrative_handoff="handoff",
            recommended_opening_focus="focus",
            intervention_evidence=(later, earlier),
        )
