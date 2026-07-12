"""Pure merge and no-op detection for post-session patches."""

from __future__ import annotations

from typing import Any

from jung.domain.models import Plan, PlanContent
from jung.phases.post_session.models import (
    DerivedProfilePatch,
    PlanPatch,
    PostSessionResult,
)


def _normalize_list(values: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        item = " ".join(value.split())
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return tuple(normalized)


def _normalize_derived_profile_patch(
    patch: DerivedProfilePatch,
) -> DerivedProfilePatch:
    return DerivedProfilePatch(
        observations=_normalize_list(patch.observations),
        hypotheses=_normalize_list(patch.hypotheses),
        patient_stated_facts=_normalize_list(patch.patient_stated_facts),
    )


def derived_profile_patch_is_empty(patch: DerivedProfilePatch) -> bool:
    normalized = _normalize_derived_profile_patch(patch)
    return not (
        normalized.observations
        or normalized.hypotheses
        or normalized.patient_stated_facts
    )


def merge_derived_profile(
    current: dict[str, Any] | None,
    patch: DerivedProfilePatch,
) -> dict[str, Any] | None:
    normalized_patch = _normalize_derived_profile_patch(patch)
    if derived_profile_patch_is_empty(normalized_patch):
        return current

    merged: dict[str, Any] = dict(current or {})
    for field_name in (
        "observations",
        "hypotheses",
        "patient_stated_facts",
    ):
        incoming = getattr(normalized_patch, field_name)
        if not incoming:
            continue
        existing = tuple(merged.get(field_name, ()))
        merged[field_name] = list(_normalize_list(existing + incoming))
    return merged


def derived_profile_changed(
    current: dict[str, Any] | None,
    patch: DerivedProfilePatch,
) -> bool:
    return merge_derived_profile(current, patch) != current


def _current_plan_content(current: Plan) -> PlanContent:
    return PlanContent(
        focus=current.focus,
        themes=current.themes,
        goals=current.goals,
        current_progress=current.current_progress,
        planned_interventions=current.planned_interventions,
        revision_recommendations=current.revision_recommendations,
    )


def apply_plan_patch(current: Plan, patch: PlanPatch) -> PlanContent:
    return PlanContent(
        focus=patch.focus if patch.focus is not None else current.focus,
        themes=list(patch.themes if patch.themes is not None else current.themes),
        goals=list(patch.goals if patch.goals is not None else current.goals),
        current_progress=(
            patch.current_progress
            if patch.current_progress is not None
            else current.current_progress
        ),
        planned_interventions=list(
            patch.planned_interventions
            if patch.planned_interventions is not None
            else current.planned_interventions
        ),
        revision_recommendations=list(
            patch.revision_recommendations
            if patch.revision_recommendations is not None
            else current.revision_recommendations
        ),
    )


def plan_patch_is_noop(current: Plan, patch: PlanPatch) -> bool:
    return apply_plan_patch(current, patch) == _current_plan_content(current)


def merge_plan_content(
    current: Plan,
    patch: PlanPatch,
) -> PlanContent | None:
    if plan_patch_is_noop(current, patch):
        return None
    return apply_plan_patch(current, patch)


def validate_update_result(
    result: PostSessionResult,
    *,
    current_plan: Plan,
) -> PostSessionResult:
    apply_plan_patch(current_plan, result.plan_patch)
    return result
