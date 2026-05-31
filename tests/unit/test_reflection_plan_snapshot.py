from __future__ import annotations

from datetime import datetime

from psychoanalyst_app.agents.reflection.session_summary import (
    build_plan_snapshot,
    format_reflection_summary,
    is_noop_plan_update,
)
from psychoanalyst_app.models.domain import TherapyPlan
from psychoanalyst_app.models.llm_outputs import StructuredTherapyPlanOutput


def _plan_output(style: str = "cbt", progress: str = "baseline") -> StructuredTherapyPlanOutput:
    return StructuredTherapyPlanOutput(
        selected_therapy_style=style,
        plan_details={"focus": "anxiety"},
        initial_goals=["Reduce anxiety"],
        current_progress=progress,
        planned_interventions=["Supportive listening"],
        status="active",
    )


def _current_plan() -> TherapyPlan:
    return TherapyPlan(
        plan_id="plan_1",
        user_id="user_1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        version=2,
        selected_therapy_style="cbt",
        plan_details={"focus": "anxiety"},
        initial_goals=["Reduce anxiety"],
        current_progress="baseline",
        planned_interventions=["Supportive listening"],
        status="active",
    )


def test_is_noop_plan_update_detects_exact_match() -> None:
    plan = _current_plan()
    assert is_noop_plan_update(plan, _plan_output()) is True
    assert is_noop_plan_update(plan, _plan_output(progress="changed")) is False


def test_build_plan_snapshot_keeps_or_increments_version() -> None:
    plan = _current_plan()

    noop_snapshot = build_plan_snapshot(plan, _plan_output(), user_id="user_1")
    assert noop_snapshot.version == 2

    changed_snapshot = build_plan_snapshot(
        plan,
        _plan_output(progress="new progress"),
        user_id="user_1",
    )
    assert changed_snapshot.version == 3



def test_build_plan_snapshot_creates_pending_plan_when_missing_current() -> None:
    snapshot = build_plan_snapshot(
        current_plan=None,
        plan_output=_plan_output(style="jung"),
        user_id="user_2",
    )
    assert snapshot.plan_id.startswith("pending_")
    assert snapshot.version == 1
    assert snapshot.selected_therapy_style == "jung"



def test_format_reflection_summary_renders_key_sections() -> None:
    reflection = {
        "session_context": {
            "key_themes": ["work", "anxiety"],
            "emotional_state": "anxious",
        },
        "therapeutic_memory": {
            "total_sessions": 4,
            "relationship_quality": "developing",
        },
        "plan_recommendations": [{"description": "Focus on coping"}],
    }
    summary = format_reflection_summary(reflection)
    assert "Session Reflection" in summary
    assert "Progress Overview" in summary
    assert "Focus on coping" in summary
