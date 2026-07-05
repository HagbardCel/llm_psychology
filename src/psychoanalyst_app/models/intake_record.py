"""Structured incremental intake record models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Confidence = Literal["high", "medium", "low"]
EvidenceResponseStatus = Literal["informative", "unknown", "unable_to_answer"]


class IntakeEvidence(BaseModel):
    """Patient-authored evidence for one intake field."""

    model_config = ConfigDict(extra="ignore")

    value: str | None = Field(default=None, max_length=500)
    evidence_quote: str | None = Field(default=None, max_length=500)
    source_message_index: int | None = Field(default=None, ge=0)
    source_role: Literal["user"] | None = None
    confidence: Confidence = "medium"
    response_status: EvidenceResponseStatus = "informative"
    direct_ask: bool = False

    @model_validator(mode="after")
    def validate_direct_ask_status(self) -> IntakeEvidence:
        if self.response_status != "informative" and not self.direct_ask:
            raise ValueError(
                "unknown/unable intake evidence requires direct_ask=True"
            )
        return self

    def has_patient_source(self) -> bool:
        return self.source_role == "user" and self.source_message_index is not None

    def is_addressed(self) -> bool:
        if not self.evidence_quote or not self.has_patient_source():
            return False
        if self.response_status in {"unknown", "unable_to_answer"}:
            return self.direct_ask
        return bool(self.value)

    def is_present(self) -> bool:
        return self.is_addressed() and self.response_status == "informative"

    def is_unable_or_unknown(self) -> bool:
        return self.is_addressed() and self.response_status in {
            "unknown",
            "unable_to_answer",
        }


class TimeCourseRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    duration_or_onset: IntakeEvidence = Field(default_factory=IntakeEvidence)
    frequency: IntakeEvidence = Field(default_factory=IntakeEvidence)
    trajectory: IntakeEvidence = Field(default_factory=IntakeEvidence)
    triggers: list[IntakeEvidence] = Field(default_factory=list, max_length=10)

    def has_required_time_course(self) -> bool:
        return (
            self.duration_or_onset.is_present()
            or self.frequency.is_present()
        )

    def has_addressed_time_course(self) -> bool:
        return (
            self.duration_or_onset.is_addressed()
            or self.frequency.is_addressed()
        )


class PresentingProblemRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    main_concern: IntakeEvidence = Field(default_factory=IntakeEvidence)
    symptoms: list[IntakeEvidence] = Field(default_factory=list, max_length=20)
    time_course: TimeCourseRecord = Field(default_factory=TimeCourseRecord)
    sleep_impact: IntakeEvidence = Field(default_factory=IntakeEvidence)
    functional_impairment: IntakeEvidence = Field(default_factory=IntakeEvidence)


class SafetyRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    self_harm: IntakeEvidence = Field(default_factory=IntakeEvidence)
    harm_to_others: IntakeEvidence = Field(default_factory=IntakeEvidence)
    medical_urgency: IntakeEvidence = Field(default_factory=IntakeEvidence)

    def is_complete(self) -> bool:
        return (
            self.self_harm.is_present()
            and self.harm_to_others.is_present()
            and self.medical_urgency.is_present()
        )

    def is_addressed(self) -> bool:
        return (
            self.self_harm.is_addressed()
            and self.harm_to_others.is_addressed()
            and self.medical_urgency.is_addressed()
        )


class CopingRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attempted_strategies: list[IntakeEvidence] = Field(
        default_factory=list, max_length=20
    )
    substances_or_medication: IntakeEvidence = Field(default_factory=IntakeEvidence)

    def is_present(self) -> bool:
        return bool(
            any(item.is_present() for item in self.attempted_strategies)
            or self.substances_or_medication.is_present()
        )

    def is_addressed(self) -> bool:
        return bool(
            any(item.is_addressed() for item in self.attempted_strategies)
            or self.substances_or_medication.is_addressed()
        )


class GoalsRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    therapy_goals: list[IntakeEvidence] = Field(default_factory=list, max_length=10)
    preferred_start: IntakeEvidence = Field(default_factory=IntakeEvidence)

    def is_present(self) -> bool:
        return bool(
            any(item.is_present() for item in self.therapy_goals)
            or self.preferred_start.is_present()
        )

    def is_addressed(self) -> bool:
        return bool(
            any(item.is_addressed() for item in self.therapy_goals)
            or self.preferred_start.is_addressed()
        )


class IntakeRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    presenting_problem: PresentingProblemRecord = Field(
        default_factory=PresentingProblemRecord
    )
    safety: SafetyRecord = Field(default_factory=SafetyRecord)
    coping: CopingRecord = Field(default_factory=CopingRecord)
    goals: GoalsRecord = Field(default_factory=GoalsRecord)


class IntakeRecordPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    presenting_problem: PresentingProblemRecord | None = None
    safety: SafetyRecord | None = None
    coping: CopingRecord | None = None
    goals: GoalsRecord | None = None
    no_new_information: bool = False
    rationale: str | None = Field(default=None, max_length=500)


def _count_evidence(value: Any) -> int:
    if isinstance(value, IntakeEvidence):
        return 1 if value.value or value.evidence_quote else 0
    if isinstance(value, BaseModel):
        return sum(_count_evidence(item) for item in value.__dict__.values())
    if isinstance(value, dict):
        return sum(_count_evidence(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_evidence(item) for item in value)
    return 0


def count_patch_evidence(patch: IntakeRecordPatch) -> int:
    """Count populated evidence fields on a structured intake patch."""
    return _count_evidence(patch)
