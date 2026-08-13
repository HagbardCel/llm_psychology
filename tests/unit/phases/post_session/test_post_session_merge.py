"""Post-session merge policy tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from jung.domain.models import Plan
from jung.phases.post_session.merge import merge_plan_content, plan_patch_is_noop
from jung.phases.post_session.models import PlanPatch


def _plan() -> Plan:
    now = datetime.now(UTC)
    return Plan(
        id=uuid4(),
        version=1,
        selected_style="cbt",
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=[],
        created_at=now,
    )


def test_plan_patch_noop_and_revision_merge() -> None:
    plan = _plan()
    noop_patch = PlanPatch()
    assert plan_patch_is_noop(plan, noop_patch) is True
    assert merge_plan_content(plan, noop_patch) is None

    changed = merge_plan_content(
        plan,
        PlanPatch(current_progress="improved sleep hygiene"),
    )
    assert changed is not None
    assert changed.current_progress == "improved sleep hygiene"


def test_plan_patch_replaces_listed_fields() -> None:
    plan = _plan()
    changed = merge_plan_content(
        plan,
        PlanPatch(
            focus="sleep anxiety",
            themes=("sleep",),
            goals=("rest", "worry reduction"),
            planned_interventions=("thought record",),
            revision_recommendations=("revisit goals",),
        ),
    )
    assert changed is not None
    assert changed.focus == "sleep anxiety"
    assert changed.themes == ["sleep"]
    assert changed.goals == ["rest", "worry reduction"]
    assert changed.planned_interventions == ["thought record"]
    assert changed.revision_recommendations == ["revisit goals"]
    assert changed.current_progress == plan.current_progress
