"""Processor-to-store seam integration tests."""

from __future__ import annotations

from uuid import uuid4

from jung.domain.models import NewPlanRevision, PlanContent
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult, StyleRecommendation
from jung.phases.post_session.merge import merge_derived_profile, merge_plan_content
from jung.phases.post_session.models import (
    DerivedProfilePatch,
    PlanPatch,
)

from .scenarios import advance_to_post_session, open_intake


def _plan_content(**overrides: object) -> PlanContent:
    values = {
        "focus": "anxiety",
        "themes": ["worry"],
        "goals": ["sleep"],
        "current_progress": "baseline",
        "planned_interventions": ["grounding"],
        "revision_recommendations": ["track sleep"],
    }
    values.update(overrides)
    return PlanContent(**values)


def _assessment_result() -> AssessmentResult:
    styles = ("jung", "cbt", "freud")
    return AssessmentResult(
        formulation="Anxiety presentation",
        presenting_concerns=("anxiety",),
        strengths_and_resources=("support",),
        style_recommendations=tuple(
            StyleRecommendation(
                style_id=style_id,
                score=0.9 if style_id == "cbt" else 0.5,
                rationale=f"Fit for {style_id}",
                key_topics=("anxiety",),
                initial_plan=_plan_content(),
            )
            for style_id in styles
        ),
    )


def test_assessment_initial_plan_round_trips_through_select_style(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    store.finish_intake_and_create_assessment(
        expected_revision=store.get_app_state().revision,
        intake_session_id=intake_id,
        operation_id=operation_id,
        now=now,
    )
    store.mark_operation_running(operation_id, now=now)
    store.complete_assessment(
        operation_id,
        result={"initial_plan": {"focus": "anxiety"}},
        now=now,
    )
    result = _assessment_result()
    selected = next(
        item for item in result.style_recommendations if item.style_id == "cbt"
    )

    state, plan = store.select_style_and_create_initial_plan(
        expected_revision=store.get_app_state().revision,
        style_id="cbt",
        plan_id=uuid4(),
        content=selected.initial_plan,
        intake_session_id=intake_id,
        now=now,
    )

    assert state.stage.value == "ready"
    assert plan.focus == "anxiety"
    assert plan.selected_style == "cbt"
    assert plan.version == 1


def test_post_session_merge_commits_fresh_plan_id(store: SQLiteStore) -> None:
    scenario = advance_to_post_session(store)
    previous_plan = store.get_current_plan()
    assert previous_plan is not None

    new_plan_id = uuid4()
    content = merge_plan_content(
        previous_plan,
        PlanPatch(current_progress="improved sleep hygiene"),
    )
    assert content is not None
    merged_profile = merge_derived_profile(
        store.get_profile().derived_profile if store.get_profile() else None,
        DerivedProfilePatch(),
    )

    store.mark_operation_running(scenario.post_session_operation_id, now=scenario.now)
    store.complete_post_session(
        scenario.post_session_operation_id,
        summary="steady session",
        briefing={"summary": "continuity"},
        derived_profile=merged_profile,
        new_plan=NewPlanRevision(plan_id=new_plan_id, content=content),
        now=scenario.now,
    )

    new_plan = store.get_current_plan()
    assert new_plan is not None
    assert new_plan.id == new_plan_id
    assert new_plan.id != previous_plan.id
    assert new_plan.supersedes_plan_id == previous_plan.id
    assert new_plan.current_progress == "improved sleep hygiene"
