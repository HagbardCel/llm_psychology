"""Cross-phase durable session briefing and intervention evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from jung.domain.text import normalize_content

InterventionStatus = Literal["delivered", "response_cited"]

_NARRATIVE_HANDOFF = "narrative_handoff"
_RECOMMENDED_OPENING = "recommended_opening_focus"


def _non_empty_required_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must be non-empty")
    return value


def _normalize_non_empty_content(value: str) -> str:
    value = normalize_content(value)
    if not value:
        raise ValueError("must be non-empty")
    return value


def _normalize_optional_content(value: str | None) -> str | None:
    if value is None:
        return None
    value = normalize_content(value)
    if not value:
        raise ValueError("must be non-empty when provided")
    return value


def _evidence_sort_key(
    item: InterventionEvidence,
) -> tuple[int, int]:
    return (item.therapist_sequence, item.patient_sequence or 0)


class InterventionEvidence(BaseModel):
    """Backend-resolved intervention evidence with full authoritative turns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intervention_description: str = Field(max_length=500)
    therapist_sequence: int = Field(ge=1)
    therapist_content: str
    patient_sequence: int | None = Field(default=None, ge=1)
    patient_content: str | None = None
    status: InterventionStatus

    @model_validator(mode="before")
    @classmethod
    def derive_status(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        expected: InterventionStatus = (
            "response_cited"
            if data.get("patient_sequence") is not None
            else "delivered"
        )
        if "status" in data and data["status"] != expected:
            raise ValueError("status conflicts with patient citation")
        data["status"] = expected
        return data

    @field_validator("intervention_description")
    @classmethod
    def non_empty_description(cls, value: str) -> str:
        return _non_empty_required_text(value)

    @field_validator("therapist_content")
    @classmethod
    def normalize_therapist_content(cls, value: str) -> str:
        return _normalize_non_empty_content(value)

    @field_validator("patient_content")
    @classmethod
    def normalize_patient_content(cls, value: str | None) -> str | None:
        return _normalize_optional_content(value)

    @model_validator(mode="after")
    def validate_response_reference(self) -> Self:
        sequence_present = self.patient_sequence is not None
        content_present = self.patient_content is not None
        if sequence_present != content_present:
            raise ValueError(
                "patient_sequence and patient_content must both be "
                "present or both absent"
            )
        if (
            self.patient_sequence is not None
            and self.patient_sequence <= self.therapist_sequence
        ):
            raise ValueError("patient_sequence must follow therapist_sequence")
        return self


class SessionBriefing(BaseModel):
    """Durable next-session briefing with resolved intervention evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    narrative_handoff: str
    continuity_points: tuple[str, ...] = ()
    unresolved_issues: tuple[str, ...] = ()
    recommended_opening_focus: str
    things_to_avoid: tuple[str, ...] = ()
    emotional_context: tuple[str, ...] = ()
    intervention_evidence: tuple[InterventionEvidence, ...] = ()

    @field_validator(_NARRATIVE_HANDOFF, _RECOMMENDED_OPENING)
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        return _non_empty_required_text(value)

    @model_validator(mode="after")
    def validate_evidence_integrity(self) -> Self:
        sequences = [item.therapist_sequence for item in self.intervention_evidence]
        if len(sequences) != len(set(sequences)):
            raise ValueError(
                "intervention_evidence therapist_sequence values must be unique"
            )
        canonical = tuple(sorted(self.intervention_evidence, key=_evidence_sort_key))
        if self.intervention_evidence != canonical:
            raise ValueError(
                "intervention_evidence must be in canonical order "
                "(therapist_sequence, patient_sequence or 0)"
            )
        return self


def parse_session_briefing(raw: Mapping[str, Any]) -> SessionBriefing:
    """Strictly validate a persisted briefing mapping."""
    return SessionBriefing.model_validate(raw)
