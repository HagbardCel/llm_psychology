"""Validation and merge helpers for structured intake patches."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
)

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _valid_patch_evidence(
    evidence: IntakeEvidence,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool,
) -> bool:
    if not evidence.value and not evidence.evidence_quote:
        return False
    if not evidence.value or not evidence.evidence_quote:
        return False
    if evidence.source_role != "user":
        return False
    if evidence.source_message_index != source_message_index:
        return False
    if evidence.response_status != "informative" and not evidence.direct_ask:
        return False
    if not strict_quote_validation:
        return True
    return _normalize(evidence.evidence_quote) in _normalize(
        latest_user_message.content
    )


def _merge_evidence(
    existing: IntakeEvidence,
    patch: IntakeEvidence | None,
) -> IntakeEvidence:
    if patch is None or not patch.is_addressed():
        return existing
    if not existing.is_addressed():
        return patch
    existing_rank = _CONFIDENCE_RANK[existing.confidence]
    patch_rank = _CONFIDENCE_RANK[patch.confidence]
    if patch_rank > existing_rank:
        return patch
    if (
        patch_rank == existing_rank
        and len(patch.value or "") > len(existing.value or "")
    ):
        return patch
    return existing


def _merge_evidence_list(
    existing: list[IntakeEvidence],
    patches: list[IntakeEvidence],
    *,
    max_length: int,
) -> list[IntakeEvidence]:
    merged = list(existing)
    seen = {_normalize(item.value or "") for item in merged if item.value}
    for patch in patches:
        key = _normalize(patch.value or "")
        if not key or key in seen:
            continue
        merged.append(patch)
        seen.add(key)
        if len(merged) >= max_length:
            break
    return merged


def _validated_patch_dump(
    patch: BaseModel,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool = True,
) -> dict[str, Any]:
    def clean(value: Any) -> Any:
        if isinstance(value, IntakeEvidence):
            return (
                value
                if _valid_patch_evidence(
                    value,
                    latest_user_message=latest_user_message,
                    source_message_index=source_message_index,
                    strict_quote_validation=strict_quote_validation,
                )
                else None
            )
        if isinstance(value, BaseModel):
            return {
                key: cleaned
                for key, item in value.__dict__.items()
                if (cleaned := clean(item)) not in (None, [], {})
            }
        if isinstance(value, dict):
            return {
                key: cleaned
                for key, item in value.items()
                if (cleaned := clean(item)) not in (None, [], {})
            }
        if isinstance(value, list):
            return [cleaned for item in value if (cleaned := clean(item)) is not None]
        return value

    return {
        key: cleaned
        for key, item in patch.__dict__.items()
        if (cleaned := clean(item)) not in (None, [], {})
    }


def validate_intake_record_patch(
    patch: IntakeRecordPatch,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool = True,
) -> IntakeRecordPatch:
    """Drop patch evidence that lacks valid patient quote/source support."""
    cleaned = _validated_patch_dump(
        patch,
        latest_user_message=latest_user_message,
        source_message_index=source_message_index,
        strict_quote_validation=strict_quote_validation,
    )
    return IntakeRecordPatch.model_validate(cleaned)


def merge_intake_record_patch(
    current: IntakeRecord,
    patch: IntakeRecordPatch,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool = True,
) -> IntakeRecord:
    """Return a new intake record with a conservatively validated patch applied."""
    patch = validate_intake_record_patch(
        patch,
        latest_user_message=latest_user_message,
        source_message_index=source_message_index,
        strict_quote_validation=strict_quote_validation,
    )
    merged = current.model_copy(deep=True)

    if patch.presenting_problem:
        p = patch.presenting_problem
        merged.presenting_problem.main_concern = _merge_evidence(
            merged.presenting_problem.main_concern, p.main_concern
        )
        merged.presenting_problem.symptoms = _merge_evidence_list(
            merged.presenting_problem.symptoms,
            p.symptoms,
            max_length=20,
        )
        merged.presenting_problem.sleep_impact = _merge_evidence(
            merged.presenting_problem.sleep_impact, p.sleep_impact
        )
        merged.presenting_problem.functional_impairment = _merge_evidence(
            merged.presenting_problem.functional_impairment,
            p.functional_impairment,
        )
        merged.presenting_problem.time_course.duration_or_onset = _merge_evidence(
            merged.presenting_problem.time_course.duration_or_onset,
            p.time_course.duration_or_onset,
        )
        merged.presenting_problem.time_course.frequency = _merge_evidence(
            merged.presenting_problem.time_course.frequency,
            p.time_course.frequency,
        )
        merged.presenting_problem.time_course.trajectory = _merge_evidence(
            merged.presenting_problem.time_course.trajectory,
            p.time_course.trajectory,
        )
        merged.presenting_problem.time_course.triggers = _merge_evidence_list(
            merged.presenting_problem.time_course.triggers,
            p.time_course.triggers,
            max_length=10,
        )

    if patch.safety:
        merged.safety.self_harm = _merge_evidence(
            merged.safety.self_harm, patch.safety.self_harm
        )
        merged.safety.harm_to_others = _merge_evidence(
            merged.safety.harm_to_others, patch.safety.harm_to_others
        )
        merged.safety.medical_urgency = _merge_evidence(
            merged.safety.medical_urgency, patch.safety.medical_urgency
        )

    if patch.coping:
        merged.coping.attempted_strategies = _merge_evidence_list(
            merged.coping.attempted_strategies,
            patch.coping.attempted_strategies,
            max_length=20,
        )
        merged.coping.substances_or_medication = _merge_evidence(
            merged.coping.substances_or_medication,
            patch.coping.substances_or_medication,
        )

    if patch.goals:
        merged.goals.therapy_goals = _merge_evidence_list(
            merged.goals.therapy_goals,
            patch.goals.therapy_goals,
            max_length=10,
        )
        merged.goals.preferred_start = _merge_evidence(
            merged.goals.preferred_start,
            patch.goals.preferred_start,
        )

    return merged
