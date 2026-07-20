"""Structured intake record models for phase processors."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jung.domain.models import Profile
from jung.llm.gateway import ChatMessage
from jung.phases.transcript import TranscriptTurn, normalize_transcript_content

Confidence = Literal["high", "medium", "low"]
EvidenceResponseStatus = Literal["informative", "unknown", "unable_to_answer"]


class IntakeEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str | None = Field(default=None, max_length=500)
    evidence_quote: str | None = Field(default=None, max_length=500)
    source_message_sequence: int | None = Field(default=None, ge=1)
    source_role: Literal["user"] | None = None
    confidence: Confidence = "medium"
    response_status: EvidenceResponseStatus = "informative"
    direct_ask: bool = False

    @model_validator(mode="after")
    def validate_direct_ask_status(self) -> IntakeEvidence:
        if self.response_status != "informative" and not self.direct_ask:
            raise ValueError("unknown/unable intake evidence requires direct_ask=True")
        return self

    def has_patient_source(self) -> bool:
        return self.source_role == "user" and self.source_message_sequence is not None

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
    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_or_onset: IntakeEvidence = Field(default_factory=IntakeEvidence)
    frequency: IntakeEvidence = Field(default_factory=IntakeEvidence)
    trajectory: IntakeEvidence = Field(default_factory=IntakeEvidence)
    triggers: tuple[IntakeEvidence, ...] = ()

    def has_required_time_course(self) -> bool:
        return self.duration_or_onset.is_present() or self.frequency.is_present()

    def has_addressed_time_course(self) -> bool:
        return self.duration_or_onset.is_addressed() or self.frequency.is_addressed()


class PresentingProblemRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    main_concern: IntakeEvidence = Field(default_factory=IntakeEvidence)
    symptoms: tuple[IntakeEvidence, ...] = ()
    time_course: TimeCourseRecord = Field(default_factory=TimeCourseRecord)
    sleep_impact: IntakeEvidence = Field(default_factory=IntakeEvidence)
    functional_impairment: IntakeEvidence = Field(default_factory=IntakeEvidence)


class SafetyRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

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
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempted_strategies: tuple[IntakeEvidence, ...] = ()
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
    model_config = ConfigDict(frozen=True, extra="forbid")

    therapy_goals: tuple[IntakeEvidence, ...] = ()
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
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    presenting_problem: PresentingProblemRecord = Field(
        default_factory=PresentingProblemRecord
    )
    safety: SafetyRecord = Field(default_factory=SafetyRecord)
    coping: CopingRecord = Field(default_factory=CopingRecord)
    goals: GoalsRecord = Field(default_factory=GoalsRecord)


class IntakeRecordPatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    presenting_problem: PresentingProblemRecord | None = None
    safety: SafetyRecord | None = None
    coping: CopingRecord | None = None
    goals: GoalsRecord | None = None
    no_new_information: bool = False
    rationale: str | None = Field(default=None, max_length=500)


class IntakeTurnInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: Profile
    current_record: IntakeRecord = Field(default_factory=IntakeRecord)
    transcript: tuple[TranscriptTurn, ...] = ()
    latest_user_message: str | None = None
    previous_assistant_message: str | None = None
    strict_quote_validation: bool = True
    patient_turn_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_transcript_coherence(self) -> IntakeTurnInput:
        if not self.transcript and self.latest_user_message is None:
            return self
        if not self.transcript:
            raise ValueError("latest_user_message requires a nonempty transcript")
        final_turn = self.transcript[-1]
        if final_turn.role != "user":
            raise ValueError(
                "latest_user_message requires the final transcript turn to be user"
            )
        if self.latest_user_message is None:
            raise ValueError(
                "a transcript ending in a user turn requires latest_user_message"
            )
        normalized_message = normalize_transcript_content(self.latest_user_message)
        if not normalized_message:
            raise ValueError("latest_user_message must be nonblank")
        if normalize_transcript_content(final_turn.content) != normalized_message:
            raise ValueError(
                "latest_user_message must match the final transcript user turn"
            )
        return self


class IntakeMergeDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    applied: bool
    record_changed: bool
    raw_evidence_count: int = 0
    retained_evidence_count: int = 0
    dropped_evidence_count: int = 0
    drop_reasons: tuple[dict[str, str], ...] = ()


class IntakeTurnPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    merged_record: IntakeRecord
    record_changed: bool
    completeness_complete: bool
    next_required_item: str | None = None
    max_turn_completion_blocked: bool = False
    merge_diagnostics: IntakeMergeDiagnostics | None = None
    response_messages: tuple[ChatMessage, ...] = ()
