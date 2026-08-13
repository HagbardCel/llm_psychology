"""Durable supervisor session review and related typed artifacts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MAX_EVIDENCE_ITEMS = 20

_NARRATIVE_HANDOFF = "narrative_handoff"
_RECOMMENDED_OPENING = "recommended_opening_focus"


def _non_empty_required_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must be non-empty")
    return value


class InterventionCitation(BaseModel):
    """Sequence-only intervention citation retained in the durable review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intervention_description: str = Field(max_length=500)
    therapist_sequence: int = Field(ge=1)
    patient_sequence: int | None = Field(default=None, ge=1)

    @field_validator("intervention_description")
    @classmethod
    def non_empty_description(cls, value: str) -> str:
        return _non_empty_required_text(value)


class PatientTurnCitation(BaseModel):
    """Sequence-only patient-turn citation retained in the durable review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    patient_sequence: int = Field(ge=1)


class SessionAnalysis(BaseModel):
    """Validated supervisor analysis retained on the closed therapy session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str
    key_themes: tuple[str, ...]
    dominant_affects: tuple[str, ...] = ()
    important_moments: tuple[str, ...] = ()
    patient_insights: tuple[str, ...] = ()
    progress_indicators: tuple[str, ...] = ()
    unresolved_topics: tuple[str, ...] = ()
    intervention_citations: tuple[InterventionCitation, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE_ITEMS,
    )
    patient_turn_citations: tuple[PatientTurnCitation, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE_ITEMS,
    )
    safety_or_boundary_notes: tuple[str, ...] = ()

    @field_validator("summary")
    @classmethod
    def non_empty_summary(cls, value: str) -> str:
        return _non_empty_required_text(value)


class SessionBriefing(BaseModel):
    """Next-session handoff retained inside the durable session review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    narrative_handoff: str
    continuity_points: tuple[str, ...] = ()
    unresolved_issues: tuple[str, ...] = ()
    recommended_opening_focus: str
    things_to_avoid: tuple[str, ...] = ()
    emotional_context: tuple[str, ...] = ()

    @field_validator(_NARRATIVE_HANDOFF, _RECOMMENDED_OPENING)
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        return _non_empty_required_text(value)


class PlanPatch(BaseModel):
    """Optional treatment-plan field overrides from the supervisor update pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    focus: str | None = None
    themes: tuple[str, ...] | None = None
    goals: tuple[str, ...] | None = None
    current_progress: str | None = None
    planned_interventions: tuple[str, ...] | None = None
    revision_recommendations: tuple[str, ...] | None = None


class SessionReviewGeneration(BaseModel):
    """Backend-authored provenance for conversational supervisor reviews."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    analysis_model: str
    analysis_prompt_version: str
    update_model: str
    update_prompt_version: str

    @field_validator(
        "analysis_model",
        "analysis_prompt_version",
        "update_model",
        "update_prompt_version",
    )
    @classmethod
    def non_empty_provenance(cls, value: str) -> str:
        return _non_empty_required_text(value)


class SessionReview(BaseModel):
    """Complete durable supervisor record for a completed therapy session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    analysis: SessionAnalysis
    briefing: SessionBriefing
    plan_recommendation: PlanPatch
    generation: SessionReviewGeneration | None = None
