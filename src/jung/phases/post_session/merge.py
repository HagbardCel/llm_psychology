"""Pure merge and no-op detection for post-session patches."""

from __future__ import annotations

from typing import Any

from jung.domain.grounding import parse_grounded_patient_turns
from jung.domain.models import Plan, PlanContent
from jung.phases.post_session.models import (
    DerivedProfilePatch,
    PlanPatch,
    PostSessionUpdateResult,
)


def derived_profile_patch_is_empty(patch: DerivedProfilePatch) -> bool:
    return not patch.grounded_patient_turns


def merge_derived_profile(
    current: dict[str, Any] | None,
    patch: DerivedProfilePatch,
) -> dict[str, Any] | None:
    if current is not None:
        existing = parse_grounded_patient_turns(current)
    else:
        existing = ()

    if not patch.grounded_patient_turns:
        return current

    merged: dict[str, Any] = dict(current or {})
    by_message_id = {item.source_message_id: item for item in existing}
    for item in patch.grounded_patient_turns:
        by_message_id.setdefault(item.source_message_id, item)
    merged["grounded_patient_turns"] = [
        item.model_dump(mode="json") for item in by_message_id.values()
    ]
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
    result: PostSessionUpdateResult,
    *,
    current_plan: Plan,
) -> PostSessionUpdateResult:
    apply_plan_patch(current_plan, result.plan_patch)
    return result
