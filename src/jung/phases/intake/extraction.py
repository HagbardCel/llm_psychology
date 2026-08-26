"""LLM-only intake extraction contract and Jung-owned materialization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from jung.domain.text import normalize_content
from jung.phases.intake.completion import IntakeItem, missing_items_from_record
from jung.phases.intake.models import (
    Confidence,
    CopingRecord,
    EvidenceResponseStatus,
    GoalsRecord,
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
    PresentingProblemRecord,
    SafetyRecord,
    TimeCourseRecord,
)
from jung.phases.transcript import TranscriptTurn

_LIST_FIELDS = frozenset(
    {
        "presenting_problem.symptoms",
        "presenting_problem.time_course.triggers",
        "coping.attempted_strategies",
        "goals.therapy_goals",
    }
)


class IntakeEvidenceField(StrEnum):
    PRESENTING_PROBLEM_MAIN_CONCERN = "presenting_problem.main_concern"
    PRESENTING_PROBLEM_SYMPTOMS = "presenting_problem.symptoms"
    PRESENTING_PROBLEM_DURATION_OR_ONSET = (
        "presenting_problem.time_course.duration_or_onset"
    )
    PRESENTING_PROBLEM_FREQUENCY = "presenting_problem.time_course.frequency"
    PRESENTING_PROBLEM_TRAJECTORY = "presenting_problem.time_course.trajectory"
    PRESENTING_PROBLEM_TRIGGERS = "presenting_problem.time_course.triggers"
    PRESENTING_PROBLEM_SLEEP_IMPACT = "presenting_problem.sleep_impact"
    PRESENTING_PROBLEM_FUNCTIONAL_IMPAIRMENT = (
        "presenting_problem.functional_impairment"
    )
    SAFETY_SELF_HARM = "safety.self_harm"
    SAFETY_HARM_TO_OTHERS = "safety.harm_to_others"
    SAFETY_MEDICAL_URGENCY = "safety.medical_urgency"
    COPING_ATTEMPTED_STRATEGIES = "coping.attempted_strategies"
    COPING_SUBSTANCES_OR_MEDICATION = "coping.substances_or_medication"
    GOALS_THERAPY_GOALS = "goals.therapy_goals"
    GOALS_PREFERRED_START = "goals.preferred_start"


FIELD_TO_INTAKE_ITEM: Mapping[IntakeEvidenceField, IntakeItem | None] = {
    IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN: "presenting_problem",
    IntakeEvidenceField.PRESENTING_PROBLEM_SYMPTOMS: None,
    IntakeEvidenceField.PRESENTING_PROBLEM_DURATION_OR_ONSET: "duration",
    IntakeEvidenceField.PRESENTING_PROBLEM_FREQUENCY: "duration",
    IntakeEvidenceField.PRESENTING_PROBLEM_TRAJECTORY: None,
    IntakeEvidenceField.PRESENTING_PROBLEM_TRIGGERS: None,
    IntakeEvidenceField.PRESENTING_PROBLEM_SLEEP_IMPACT: "sleep_impact",
    IntakeEvidenceField.PRESENTING_PROBLEM_FUNCTIONAL_IMPAIRMENT: (
        "functional_impairment"
    ),
    IntakeEvidenceField.SAFETY_SELF_HARM: "risk_screen",
    IntakeEvidenceField.SAFETY_HARM_TO_OTHERS: "risk_screen",
    IntakeEvidenceField.SAFETY_MEDICAL_URGENCY: "risk_screen",
    IntakeEvidenceField.COPING_ATTEMPTED_STRATEGIES: "coping_attempts",
    IntakeEvidenceField.COPING_SUBSTANCES_OR_MEDICATION: "coping_attempts",
    IntakeEvidenceField.GOALS_THERAPY_GOALS: "goal_preference",
    IntakeEvidenceField.GOALS_PREFERRED_START: "goal_preference",
}


class ExtractedIntakeEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: IntakeEvidenceField
    value: str | None = Field(default=None, max_length=500)
    evidence_quote: str = Field(min_length=1, max_length=500)
    confidence: Confidence = "medium"
    response_status: EvidenceResponseStatus = "informative"


class IntakeExtraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: tuple[ExtractedIntakeEvidence, ...] = Field(default=(), max_length=25)


@dataclass(frozen=True, slots=True)
class IntakeMaterializationResult:
    patch: IntakeRecordPatch
    raw_candidate_count: int
    materialized_candidate_count: int
    drop_reasons: tuple[dict[str, str], ...]


def prompted_item_for_extraction(
    record: IntakeRecord,
    *,
    patient_turn_count: int,
) -> IntakeItem | None:
    if patient_turn_count == 1:
        return "presenting_problem"
    return missing_items_from_record(record).next_required_item


def materialize_extraction(
    extraction: IntakeExtraction,
    *,
    latest_user_turn: TranscriptTurn,
    prompted_item: IntakeItem | None,
) -> IntakeMaterializationResult:
    drop_reasons: list[dict[str, str]] = []
    scalars: dict[IntakeEvidenceField, IntakeEvidence] = {}
    lists: dict[IntakeEvidenceField, list[IntakeEvidence]] = {
        field: []
        for field in (
            IntakeEvidenceField.PRESENTING_PROBLEM_SYMPTOMS,
            IntakeEvidenceField.PRESENTING_PROBLEM_TRIGGERS,
            IntakeEvidenceField.COPING_ATTEMPTED_STRATEGIES,
            IntakeEvidenceField.GOALS_THERAPY_GOALS,
        )
    }

    for index, candidate in enumerate(extraction.evidence):
        normalized_quote = normalize_content(candidate.evidence_quote)
        if not normalized_quote:
            drop_reasons.append(
                {"field_path": f"evidence[{index}]", "reason": "missing_evidence_quote"}
            )
            continue

        intake_item = FIELD_TO_INTAKE_ITEM[candidate.field]
        direct_ask = intake_item is not None and intake_item == prompted_item
        if candidate.response_status != "informative" and (
            intake_item is None or intake_item != prompted_item
        ):
            drop_reasons.append(
                {
                    "field_path": f"evidence[{index}]",
                    "reason": "unasked_noninformative",
                }
            )
            continue

        normalized_value = (
            None
            if candidate.value is None
            else (normalize_content(candidate.value) or None)
        )
        evidence = IntakeEvidence(
            value=normalized_value,
            evidence_quote=normalized_quote,
            source_message_sequence=latest_user_turn.sequence,
            source_role="user",
            confidence=candidate.confidence,
            response_status=candidate.response_status,
            direct_ask=direct_ask,
        )

        if candidate.field.value in _LIST_FIELDS:
            lists[candidate.field].append(evidence)
            continue

        if candidate.field in scalars:
            drop_reasons.append(
                {
                    "field_path": f"evidence[{index}]",
                    "reason": "duplicate_scalar_field",
                }
            )
            continue
        scalars[candidate.field] = evidence

    patch = _build_patch(scalars=scalars, lists=lists)
    materialized_candidate_count = sum(1 for _ in _iter_patch_evidence(patch))
    raw_candidate_count = len(extraction.evidence)
    assert raw_candidate_count == materialized_candidate_count + len(drop_reasons)
    return IntakeMaterializationResult(
        patch=patch,
        raw_candidate_count=raw_candidate_count,
        materialized_candidate_count=materialized_candidate_count,
        drop_reasons=tuple(drop_reasons),
    )


def _iter_patch_evidence(patch: IntakeRecordPatch):
    if patch.presenting_problem is not None:
        p = patch.presenting_problem
        yield from _yield_if_addressed(p.main_concern)
        yield from p.symptoms
        yield from _yield_if_addressed(p.sleep_impact)
        yield from _yield_if_addressed(p.functional_impairment)
        tc = p.time_course
        yield from _yield_if_addressed(tc.duration_or_onset)
        yield from _yield_if_addressed(tc.frequency)
        yield from _yield_if_addressed(tc.trajectory)
        yield from tc.triggers
    if patch.safety is not None:
        s = patch.safety
        yield from _yield_if_addressed(s.self_harm)
        yield from _yield_if_addressed(s.harm_to_others)
        yield from _yield_if_addressed(s.medical_urgency)
    if patch.coping is not None:
        c = patch.coping
        yield from c.attempted_strategies
        yield from _yield_if_addressed(c.substances_or_medication)
    if patch.goals is not None:
        g = patch.goals
        yield from g.therapy_goals
        yield from _yield_if_addressed(g.preferred_start)


def _yield_if_addressed(evidence: IntakeEvidence):
    if evidence.value or evidence.evidence_quote:
        yield evidence


def _build_patch(
    *,
    scalars: Mapping[IntakeEvidenceField, IntakeEvidence],
    lists: Mapping[IntakeEvidenceField, list[IntakeEvidence]],
) -> IntakeRecordPatch:
    presenting_updates: dict[str, object] = {}
    time_course_updates: dict[str, object] = {}
    safety_updates: dict[str, object] = {}
    coping_updates: dict[str, object] = {}
    goals_updates: dict[str, object] = {}

    mapping: list[tuple[IntakeEvidenceField, dict[str, object], str]] = [
        (
            IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
            presenting_updates,
            "main_concern",
        ),
        (
            IntakeEvidenceField.PRESENTING_PROBLEM_SLEEP_IMPACT,
            presenting_updates,
            "sleep_impact",
        ),
        (
            IntakeEvidenceField.PRESENTING_PROBLEM_FUNCTIONAL_IMPAIRMENT,
            presenting_updates,
            "functional_impairment",
        ),
        (
            IntakeEvidenceField.PRESENTING_PROBLEM_DURATION_OR_ONSET,
            time_course_updates,
            "duration_or_onset",
        ),
        (
            IntakeEvidenceField.PRESENTING_PROBLEM_FREQUENCY,
            time_course_updates,
            "frequency",
        ),
        (
            IntakeEvidenceField.PRESENTING_PROBLEM_TRAJECTORY,
            time_course_updates,
            "trajectory",
        ),
        (IntakeEvidenceField.SAFETY_SELF_HARM, safety_updates, "self_harm"),
        (IntakeEvidenceField.SAFETY_HARM_TO_OTHERS, safety_updates, "harm_to_others"),
        (
            IntakeEvidenceField.SAFETY_MEDICAL_URGENCY,
            safety_updates,
            "medical_urgency",
        ),
        (
            IntakeEvidenceField.COPING_SUBSTANCES_OR_MEDICATION,
            coping_updates,
            "substances_or_medication",
        ),
        (IntakeEvidenceField.GOALS_PREFERRED_START, goals_updates, "preferred_start"),
    ]
    for field, target, key in mapping:
        if field in scalars:
            target[key] = scalars[field]

    symptoms = tuple(lists[IntakeEvidenceField.PRESENTING_PROBLEM_SYMPTOMS])
    if symptoms:
        presenting_updates["symptoms"] = symptoms
    triggers = tuple(lists[IntakeEvidenceField.PRESENTING_PROBLEM_TRIGGERS])
    if triggers:
        time_course_updates["triggers"] = triggers
    strategies = tuple(lists[IntakeEvidenceField.COPING_ATTEMPTED_STRATEGIES])
    if strategies:
        coping_updates["attempted_strategies"] = strategies
    therapy_goals = tuple(lists[IntakeEvidenceField.GOALS_THERAPY_GOALS])
    if therapy_goals:
        goals_updates["therapy_goals"] = therapy_goals

    if time_course_updates:
        presenting_updates["time_course"] = TimeCourseRecord(**time_course_updates)

    presenting = (
        PresentingProblemRecord(**presenting_updates) if presenting_updates else None
    )
    safety = SafetyRecord(**safety_updates) if safety_updates else None
    coping = CopingRecord(**coping_updates) if coping_updates else None
    goals = GoalsRecord(**goals_updates) if goals_updates else None

    if presenting is None and safety is None and coping is None and goals is None:
        return IntakeRecordPatch()
    return IntakeRecordPatch(
        presenting_problem=presenting,
        safety=safety,
        coping=coping,
        goals=goals,
    )
