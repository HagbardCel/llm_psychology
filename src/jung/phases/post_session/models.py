"""Post-session phase models."""

from __future__ import annotations

from itertools import pairwise
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from jung.domain.models import Plan, Profile
from jung.phases.transcript import TranscriptTurn
from jung.styles import StyleDefinition

InterventionStatus = Literal["delivered", "responded"]

_MAX_EVIDENCE_ITEMS = 20


def _non_empty_required_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must be non-empty")
    return value


def _non_empty_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("must be non-empty when provided")
    return value


class InterventionEvidence(BaseModel):
    """Transcript-grounded intervention citation.

    ``intervention_description`` is a model-generated interpretation. The
    backend validates the cited turn sequences and verbatim quotes; it does not
    verify that the description is a canonical clinical category.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    intervention_description: str = Field(max_length=500)
    therapist_sequence: int = Field(ge=1)
    therapist_quote: str = Field(max_length=500)
    patient_sequence: int | None = Field(default=None, ge=1)
    patient_quote: str | None = Field(default=None, max_length=500)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> InterventionStatus:
        return "responded" if self.patient_sequence is not None else "delivered"

    @field_validator("intervention_description", "therapist_quote")
    @classmethod
    def non_empty_required_text(cls, value: str) -> str:
        return _non_empty_required_text(value)

    @field_validator("patient_quote")
    @classmethod
    def non_empty_optional_text(cls, value: str | None) -> str | None:
        return _non_empty_optional_text(value)

    @model_validator(mode="after")
    def validate_patient_fields_together(self) -> InterventionEvidence:
        has_sequence = self.patient_sequence is not None
        has_quote = self.patient_quote is not None
        if has_sequence != has_quote:
            raise ValueError(
                "patient_sequence and patient_quote must both be present or both absent"
            )
        return self


class PatientStatementCitation(BaseModel):
    """Model-facing citation of a patient utterance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    patient_sequence: int = Field(ge=1)
    patient_quote: str = Field(max_length=500)

    @field_validator("patient_quote")
    @classmethod
    def non_empty_quote(cls, value: str) -> str:
        return _non_empty_required_text(value)


class GroundedPatientStatement(BaseModel):
    """Durable grounded patient utterance with authoritative message identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_message_id: UUID
    source_sequence: int = Field(ge=1)
    quote: str = Field(max_length=500)

    @field_validator("quote")
    @classmethod
    def non_empty_quote(cls, value: str) -> str:
        return _non_empty_required_text(value)


class SessionAnalysisResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str
    key_themes: tuple[str, ...]
    dominant_affects: tuple[str, ...] = ()
    important_moments: tuple[str, ...] = ()
    patient_insights: tuple[str, ...] = ()
    progress_indicators: tuple[str, ...] = ()
    unresolved_topics: tuple[str, ...] = ()
    intervention_evidence: tuple[InterventionEvidence, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE_ITEMS,
    )
    patient_statements: tuple[PatientStatementCitation, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE_ITEMS,
    )
    safety_or_boundary_notes: tuple[str, ...] = ()

    @field_validator("summary")
    @classmethod
    def non_empty_summary(cls, value: str) -> str:
        return _non_empty_required_text(value)


class SessionBriefingDraft(BaseModel):
    """Update-call briefing fields without intervention evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    narrative_handoff: str
    continuity_points: tuple[str, ...] = ()
    unresolved_issues: tuple[str, ...] = ()
    recommended_opening_focus: str
    things_to_avoid: tuple[str, ...] = ()
    emotional_context: tuple[str, ...] = ()

    @field_validator("narrative_handoff", "recommended_opening_focus")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        return _non_empty_required_text(value)


class SessionBriefing(SessionBriefingDraft):
    intervention_evidence: tuple[InterventionEvidence, ...] = ()


class DerivedProfilePatch(BaseModel):
    """Processor-composed durable profile patch.

    Contains grounded patient utterances only — not verified facts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    grounded_patient_statements: tuple[GroundedPatientStatement, ...] = ()


class PlanPatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    focus: str | None = None
    themes: tuple[str, ...] | None = None
    goals: tuple[str, ...] | None = None
    current_progress: str | None = None
    planned_interventions: tuple[str, ...] | None = None
    revision_recommendations: tuple[str, ...] | None = None


class PostSessionUpdateResult(BaseModel):
    """Update-call schema: briefing draft and plan patch only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_briefing: SessionBriefingDraft
    plan_patch: PlanPatch


class PostSessionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_summary: str
    session_briefing: SessionBriefing
    derived_profile_patch: DerivedProfilePatch
    plan_patch: PlanPatch

    @field_validator("session_summary")
    @classmethod
    def non_empty_session_summary(cls, value: str) -> str:
        return _non_empty_required_text(value)


class PostSessionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    transcript: tuple[TranscriptTurn, ...]
    current_plan: Plan
    profile: Profile
    derived_profile: dict[str, Any] | None = None
    prior_session_briefing: dict[str, Any] | None = None
    recent_session_summaries: tuple[str, ...] = ()
    selected_style: StyleDefinition

    @model_validator(mode="after")
    def validate_style_matches_plan(self) -> PostSessionInput:
        if self.selected_style.id != self.current_plan.selected_style:
            raise ValueError("selected_style must match current_plan.selected_style")
        return self

    @model_validator(mode="after")
    def validate_transcript_identity(self) -> PostSessionInput:
        sequences = [turn.sequence for turn in self.transcript]
        if any(current >= following for current, following in pairwise(sequences)):
            raise ValueError(
                "transcript sequences must be unique and strictly increasing"
            )
        message_ids = [turn.message_id for turn in self.transcript]
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("transcript message IDs must be unique")
        return self
