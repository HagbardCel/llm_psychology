"""Pure merge and no-op detection for post-session patches."""

from __future__ import annotations

from typing import Any

from jung.domain.models import NewPlanRevision, Plan, PlanContent
from jung.phases.post_session.models import DerivedProfilePatch, PlanPatch


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


def _normalize_plan_content(content: PlanContent) -> PlanContent:
    return PlanContent(
        focus=content.focus.strip(),
        themes=list(_normalize_list(tuple(content.themes))),
        goals=list(_normalize_list(tuple(content.goals))),
        current_progress=content.current_progress.strip(),
        planned_interventions=list(
            _normalize_list(tuple(content.planned_interventions))
        ),
        revision_recommendations=list(
            _normalize_list(tuple(content.revision_recommendations))
        ),
    )


def merge_derived_profile(
    current: dict[str, Any] | None,
    patch: DerivedProfilePatch,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(current or {})
    for field_name in (
        "observations",
        "hypotheses",
        "patient_stated_facts",
    ):
        existing = tuple(merged.get(field_name, ()))
        incoming = getattr(patch, field_name)
        merged[field_name] = list(_normalize_list(existing + incoming))
    return merged


def derived_profile_changed(
    current: dict[str, Any] | None,
    patch: DerivedProfilePatch,
) -> bool:
    return merge_derived_profile(current, patch) != dict(current or {})


def apply_plan_patch(current: Plan, patch: PlanPatch) -> PlanContent:
    content = PlanContent(
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
    return _normalize_plan_content(content)


def plan_patch_is_noop(current: Plan, patch: PlanPatch) -> bool:
    candidate = apply_plan_patch(current, patch)
    current_content = _normalize_plan_content(
        PlanContent(
            focus=current.focus,
            themes=current.themes,
            goals=current.goals,
            current_progress=current.current_progress,
            planned_interventions=current.planned_interventions,
            revision_recommendations=current.revision_recommendations,
        )
    )
    return candidate == current_content


def merge_plan_revision(
    current: Plan,
    patch: PlanPatch,
) -> NewPlanRevision | None:
    if plan_patch_is_noop(current, patch):
        return None
    return NewPlanRevision(
        plan_id=current.id,
        content=apply_plan_patch(current, patch),
    )
