"""Deterministic completeness evaluation for structured intake records."""

from __future__ import annotations

from pydantic import BaseModel, Field

from psychoanalyst_app.agents.intake.policy import (
    MAX_INTAKE_PATIENT_TURNS,
    MIN_INTAKE_PATIENT_TURNS,
)
from psychoanalyst_app.models.intake_record import IntakeEvidence, IntakeRecord

HARD_ITEM_ORDER = [
    "risk_screen",
    "presenting_problem",
    "duration",
    "functional_impairment",
    "goal_preference",
]
SOFT_ITEM_ORDER = ["coping_attempts", "sleep_impact"]
ITEM_ORDER = HARD_ITEM_ORDER + SOFT_ITEM_ORDER


class IntakeCompleteness(BaseModel):
    complete: bool
    missing_required_items: list[str] = Field(default_factory=list)
    missing_hard_items: list[str] = Field(default_factory=list)
    missing_soft_items: list[str] = Field(default_factory=list)
    directly_asked_items: list[str] = Field(default_factory=list)
    unable_to_answer_items: list[str] = Field(default_factory=list)
    addressed_hard_items: list[str] = Field(default_factory=list)
    next_required_item: str | None = None
    max_turn_completion: bool = False


def _item_evidence(record: IntakeRecord, item: str) -> list[IntakeEvidence]:
    if item == "risk_screen":
        return [
            record.safety.self_harm,
            record.safety.harm_to_others,
            record.safety.medical_urgency,
        ]
    if item == "presenting_problem":
        return [record.presenting_problem.main_concern]
    if item == "duration":
        return [
            record.presenting_problem.time_course.duration_or_onset,
            record.presenting_problem.time_course.frequency,
        ]
    if item == "functional_impairment":
        return [record.presenting_problem.functional_impairment]
    if item == "goal_preference":
        return [
            *record.goals.therapy_goals,
            record.goals.preferred_start,
        ]
    if item == "coping_attempts":
        return [
            *record.coping.attempted_strategies,
            record.coping.substances_or_medication,
        ]
    if item == "sleep_impact":
        return [record.presenting_problem.sleep_impact]
    return []


def _has_informative(record: IntakeRecord, item: str) -> bool:
    if item == "risk_screen":
        return record.safety.is_complete()
    if item == "duration":
        return record.presenting_problem.time_course.has_required_time_course()
    if item == "goal_preference":
        return record.goals.is_present()
    if item == "coping_attempts":
        return record.coping.is_present()
    return any(evidence.is_present() for evidence in _item_evidence(record, item))


def _has_addressed(record: IntakeRecord, item: str) -> bool:
    if item == "risk_screen":
        return record.safety.is_addressed()
    if item == "duration":
        return record.presenting_problem.time_course.has_addressed_time_course()
    if item == "goal_preference":
        return record.goals.is_addressed()
    if item == "coping_attempts":
        return record.coping.is_addressed()
    return any(evidence.is_addressed() for evidence in _item_evidence(record, item))


def _was_directly_asked(record: IntakeRecord, item: str) -> bool:
    return any(evidence.direct_ask for evidence in _item_evidence(record, item))


def _has_unable_or_unknown(record: IntakeRecord, item: str) -> bool:
    return any(
        evidence.is_unable_or_unknown() for evidence in _item_evidence(record, item)
    )


def _still_needs_direct_ask(record: IntakeRecord, item: str) -> bool:
    """Whether structured gate should still target this item."""
    if _has_informative(record, item):
        return False
    if _was_directly_asked(record, item) and _has_addressed(record, item):
        return False
    return True


def missing_items_from_record(record: IntakeRecord) -> IntakeCompleteness:
    """Return missing-item diagnostics without applying turn-count policy."""
    missing_hard = [
        item for item in HARD_ITEM_ORDER if not _has_informative(record, item)
    ]
    missing_soft = [
        item for item in SOFT_ITEM_ORDER if not _has_informative(record, item)
    ]
    directly_asked = [item for item in ITEM_ORDER if _was_directly_asked(record, item)]
    unable = [item for item in ITEM_ORDER if _has_unable_or_unknown(record, item)]
    addressed_hard = [item for item in HARD_ITEM_ORDER if _has_addressed(record, item)]
    missing_required = missing_hard + missing_soft
    next_required_item = next(
        (item for item in ITEM_ORDER if _still_needs_direct_ask(record, item)),
        None,
    )
    return IntakeCompleteness(
        complete=False,
        missing_required_items=missing_required,
        missing_hard_items=missing_hard,
        missing_soft_items=missing_soft,
        directly_asked_items=directly_asked,
        unable_to_answer_items=unable,
        addressed_hard_items=addressed_hard,
        next_required_item=next_required_item,
    )


def intake_record_completion_decision(
    record: IntakeRecord,
    patient_turn_count: int,
) -> IntakeCompleteness:
    """Evaluate intake completion from structured state and turn policy."""
    diagnostics = missing_items_from_record(record)
    missing_hard = set(diagnostics.missing_hard_items)
    missing_soft = set(diagnostics.missing_soft_items)
    addressed_hard = set(diagnostics.addressed_hard_items)
    hard_items = set(HARD_ITEM_ORDER)

    all_hard_informative = not missing_hard
    all_hard_items_addressed = hard_items <= addressed_hard
    max_turn_completion = (
        patient_turn_count >= MAX_INTAKE_PATIENT_TURNS
        and all_hard_items_addressed
        and bool(missing_soft or missing_hard)
    )
    complete = (
        all_hard_informative
        and not missing_soft
        and patient_turn_count >= MIN_INTAKE_PATIENT_TURNS
    ) or max_turn_completion

    return diagnostics.model_copy(
        update={
            "complete": complete,
            "max_turn_completion": max_turn_completion,
        }
    )
