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
    count_patch_evidence,
)

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}

MAX_INTAKE_DROP_REASONS = 25

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
    ``drop_reasons`` explains why individual evidence fields were rejected
    during validation (bounded by ``MAX_INTAKE_DROP_REASONS``).
    """

    record: IntakeRecord
    status: IntakePatchMergeStatus
    applied: bool
    raw_evidence_count: int
    retained_evidence_count: int
    dropped_evidence_count: int
    record_changed: bool
    drop_reasons: tuple[dict[str, str], ...] = ()
    drop_reasons_total: int = 0
    drop_reasons_truncated: bool = False
    error_message: str | None = None
    error_code: str | None = None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _evidence_drop_reason(
    evidence: IntakeEvidence,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool,
) -> str | None:
    """Return the reason an evidence field is rejected, or ``None`` when valid."""
    if evidence.source_role != "user":
        return "source_role_not_user"
    if evidence.source_message_index != source_message_index:
        return "source_index_mismatch"
    if evidence.response_status in {"unknown", "unable_to_answer"}:
        if not evidence.direct_ask:
            return "missing_direct_ask"
        if not evidence.evidence_quote:
            return "missing_evidence_quote"
        if not strict_quote_validation:
            return None
        return (
            None
            if _normalize(evidence.evidence_quote)
            in _normalize(latest_user_message.content)
            else "quote_not_found_in_message"
        )
    if not evidence.value:
        return "missing_value"
    if not evidence.evidence_quote:
        return "missing_evidence_quote"
    if evidence.response_status != "informative" and not evidence.direct_ask:
        return "missing_direct_ask"
    if not strict_quote_validation:
        return None
    return (
        None
        if _normalize(evidence.evidence_quote)
        in _normalize(latest_user_message.content)
        else "quote_not_found_in_message"
    )


def _valid_patch_evidence(
    evidence: IntakeEvidence,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool,
) -> bool:
    return (
        _evidence_drop_reason(
            evidence,
            latest_user_message=latest_user_message,
            source_message_index=source_message_index,
            strict_quote_validation=strict_quote_validation,
        )
        is None
    )


def _merge_evidence(
    existing: IntakeEvidence,
    patch: IntakeEvidence | None,
) -> IntakeEvidence:
    if patch is None or not patch.is_addressed():
        return existing
    if not existing.is_addressed():
        return patch
    if existing.is_present() and patch.is_unable_or_unknown():
        return existing
    if existing.is_unable_or_unknown() and patch.is_present():
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
    drop_reasons: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    def clean(value: Any, path: str) -> Any:
        if isinstance(value, IntakeEvidence):
            if not (value.value or value.evidence_quote):
                return None
            reason = _evidence_drop_reason(
                value,
                latest_user_message=latest_user_message,
                source_message_index=source_message_index,
                strict_quote_validation=strict_quote_validation,
            )
            if reason is None:
                return value
            if drop_reasons is not None and path:
                drop_reasons.append({"field_path": path, "reason": reason})
            return None
        if isinstance(value, BaseModel):
            return {
                key: cleaned
                for key, item in value.__dict__.items()
                if (cleaned := clean(item, f"{path}.{key}"))
                not in (None, [], {})
            }
        if isinstance(value, dict):
            return {
                key: cleaned
                for key, item in value.items()
                if (cleaned := clean(item, f"{path}.{key}"))
                not in (None, [], {})
            }
        if isinstance(value, list):
            return [
                cleaned
                for i, item in enumerate(value)
                if (cleaned := clean(item, f"{path}[{i}]")) is not None
            ]
        return value

    return {
        key: cleaned
        for key, item in patch.__dict__.items()
        if (cleaned := clean(item, key)) not in (None, [], {})
    }


def _validate_and_collect_drop_reasons(
    patch: IntakeRecordPatch,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool = True,
) -> tuple[IntakeRecordPatch, list[dict[str, str]]]:
    drop_reasons: list[dict[str, str]] = []
    cleaned = _validated_patch_dump(
        patch,
        latest_user_message=latest_user_message,
        source_message_index=source_message_index,
        strict_quote_validation=strict_quote_validation,
        drop_reasons=drop_reasons,
    )
    return IntakeRecordPatch.model_validate(cleaned), drop_reasons


def validate_intake_record_patch(
    patch: IntakeRecordPatch,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool = True,
) -> IntakeRecordPatch:
    """Drop patch evidence that lacks valid patient quote/source support."""
    validated, _ = _validate_and_collect_drop_reasons(
        patch,
        latest_user_message=latest_user_message,
        source_message_index=source_message_index,
        strict_quote_validation=strict_quote_validation,
    )
    return validated


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


def _bound_drop_reasons(
    drop_reasons: list[dict[str, str]],
) -> tuple[tuple[dict[str, str], ...], int, bool]:
    total = len(drop_reasons)
    capped = tuple(drop_reasons[:MAX_INTAKE_DROP_REASONS])
    return capped, total, total > MAX_INTAKE_DROP_REASONS


def merge_intake_record_patch_with_diagnostics(
    current: IntakeRecord,
    patch: IntakeRecordPatch,
    *,
    latest_user_message: Message,
    source_message_index: int,
    strict_quote_validation: bool = True,
) -> IntakePatchMergeResult:
    """Merge a patch and report whether validation retained usable evidence."""
    raw_evidence_count = count_patch_evidence(patch)
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
        validated_patch, raw_drop_reasons = _validate_and_collect_drop_reasons(
            patch,
            latest_user_message=latest_user_message,
            source_message_index=source_message_index,
            strict_quote_validation=strict_quote_validation,
        )
        retained_evidence_count = count_patch_evidence(validated_patch)
        dropped_evidence_count = raw_evidence_count - retained_evidence_count
        capped_reasons, drop_total, truncated = _bound_drop_reasons(raw_drop_reasons)
        if raw_evidence_count > 0 and retained_evidence_count == 0:
            return IntakePatchMergeResult(
                record=current,
                status="empty_after_validation",
                applied=False,
                raw_evidence_count=raw_evidence_count,
                retained_evidence_count=retained_evidence_count,
                dropped_evidence_count=dropped_evidence_count,
                record_changed=False,
                drop_reasons=capped_reasons,
                drop_reasons_total=drop_total,
                drop_reasons_truncated=truncated,
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
        drop_reasons=capped_reasons,
        drop_reasons_total=drop_total,
        drop_reasons_truncated=truncated,
    )
