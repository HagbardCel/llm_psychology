"""Validation and merge helpers for structured intake patches."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
)

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}

IntakePatchMergeStatus = Literal[
    "applied",
    "empty_patch",
    "empty_after_validation",
    "merge_failure",
]


@dataclass(frozen=True)
class IntakePatchMergeResult:
    """Result of validating and merging a structured intake patch.

    ``applied`` means validated evidence reached the deterministic merge path.
    ``record_changed`` is the persistence-relevant signal.
    """

    record: IntakeRecord
    status: IntakePatchMergeStatus
    applied: bool
    raw_evidence_count: int
    retained_evidence_count: int
    dropped_evidence_count: int
    record_changed: bool
    error_message: str | None = None
    error_code: str | None = None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _valid_patch_evidence(
    evidence: IntakeEvidence,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool,
) -> bool:
    if evidence.source_role != "user":
        return False
    if evidence.source_message_index != source_message_index:
        return False
    if evidence.response_status in {"unknown", "unable_to_answer"}:
        if not evidence.direct_ask or not evidence.evidence_quote:
            return False
        if not strict_quote_validation:
            return True
        return _normalize(evidence.evidence_quote) in _normalize(
            latest_user_message.content
        )
    if not evidence.value or not evidence.evidence_quote:
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


def _evidence_list_key(item: IntakeEvidence) -> str:
    if item.value:
        return f"value:{_normalize(item.value)}"
    if item.evidence_quote:
        return f"quote:{_normalize(item.evidence_quote)}"
    return ""


def _merge_evidence_list(
    existing: list[IntakeEvidence],
    patches: list[IntakeEvidence],
    *,
    max_length: int,
) -> list[IntakeEvidence]:
    merged = list(existing)
    seen = {
        key
        for item in merged
        if (key := _evidence_list_key(item))
    }
    for patch in patches:
        key = _evidence_list_key(patch)
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


def count_patch_evidence(patch: IntakeRecordPatch) -> int:
    """Count populated evidence fields on a structured intake patch."""
    return _count_evidence(patch)


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
    return _merge_validated_patch(current, patch)


def _merge_validated_patch(
    current: IntakeRecord,
    patch: IntakeRecordPatch,
) -> IntakeRecord:
    """Return a new intake record with an already validated patch applied."""
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


def merge_intake_record_patch_with_diagnostics(
    current: IntakeRecord,
    patch: IntakeRecordPatch,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool = True,
) -> IntakePatchMergeResult:
    """Merge a patch and report whether validation retained usable evidence."""
    raw_evidence_count = _count_evidence(patch)
    if raw_evidence_count == 0:
        return IntakePatchMergeResult(
            record=current,
            status="empty_patch",
            applied=False,
            raw_evidence_count=0,
            retained_evidence_count=0,
            dropped_evidence_count=0,
            record_changed=False,
        )

    try:
        validated_patch = validate_intake_record_patch(
            patch,
            latest_user_message=latest_user_message,
            source_message_index=source_message_index,
            strict_quote_validation=strict_quote_validation,
        )
        retained_evidence_count = _count_evidence(validated_patch)
        dropped_evidence_count = raw_evidence_count - retained_evidence_count
        if raw_evidence_count > 0 and retained_evidence_count == 0:
            return IntakePatchMergeResult(
                record=current,
                status="empty_after_validation",
                applied=False,
                raw_evidence_count=raw_evidence_count,
                retained_evidence_count=retained_evidence_count,
                dropped_evidence_count=dropped_evidence_count,
                record_changed=False,
            )

        merged = _merge_validated_patch(current, validated_patch)
    except Exception as exc:
        return IntakePatchMergeResult(
            record=current,
            status="merge_failure",
            applied=False,
            raw_evidence_count=raw_evidence_count,
            retained_evidence_count=0,
            dropped_evidence_count=raw_evidence_count,
            record_changed=False,
            error_message=str(exc),
            error_code=type(exc).__name__,
        )
    record_changed = merged != current

    return IntakePatchMergeResult(
        record=merged,
        status="applied",
        applied=True,
        raw_evidence_count=raw_evidence_count,
        retained_evidence_count=retained_evidence_count,
        dropped_evidence_count=dropped_evidence_count,
        record_changed=record_changed,
    )
