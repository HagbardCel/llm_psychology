from datetime import datetime

from psychoanalyst_app.agents.planning.formatting import format_therapy_plan
from psychoanalyst_app.models.domain import TherapyPlan


def test_format_therapy_plan_preserves_typed_items_without_truncation() -> None:
    goals = ["Week 6. Review progress", *[f"Goal {index}" for index in range(1, 7)]]
    techniques = [f"Technique {index}" for index in range(1, 8)]
    formatted = format_therapy_plan(
        TherapyPlan(
            user_id="user_1",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            focus="Anxiety",
            themes=["Work stress"],
            timeline="Eight weeks",
            initial_goals=goals,
            current_progress="Baseline",
            planned_interventions=techniques,
        )
    )

    assert "Week 6. Review progress" in formatted
    assert "Goal 6" in formatted
    assert "Technique 7" in formatted
