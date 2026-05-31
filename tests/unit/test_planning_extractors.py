from psychoanalyst_app.agents.planning.extraction import _plan_update_details
from psychoanalyst_app.models.llm_outputs import PlanUpdate


def test_plan_update_details_preserve_typed_items_without_truncation() -> None:
    goals = ["Week 6. Review progress", *[f"Goal {index}" for index in range(1, 7)]]
    techniques = [f"Technique {index}" for index in range(1, 8)]
    details = _plan_update_details(
        PlanUpdate(
            focus="Anxiety",
            goals=goals,
            techniques=techniques,
            themes="Work stress",
            timeline="Eight weeks",
        )
    )

    assert "Week 6. Review progress" in details["goals"]
    assert details["goals"].count("\n") == len(goals) - 1
    assert details["techniques"].count("\n") == len(techniques) - 1
