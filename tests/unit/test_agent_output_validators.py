from datetime import datetime

from psychoanalyst_app.models.domain import UserProfile
from psychoanalyst_app.orchestration.agent_output_validators import (
    build_therapy_plan_output,
    build_user_profile_output,
    is_profile_complete,
)


def test_build_user_profile_output_defaults():
    output = build_user_profile_output({"name": "Alice"})

    assert output.name == "Alice"
    assert output.primary_language == "English"


def test_build_user_profile_output_parses_date():
    output = build_user_profile_output({"date_of_birth": "1990-01-02"})

    assert isinstance(output.date_of_birth, datetime)


def test_is_profile_complete_requires_non_guest_name():
    incomplete = UserProfile(
        user_id="guest_user",
        name="Guest",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    complete = UserProfile(
        user_id="user_123",
        name="Alex",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    assert is_profile_complete(incomplete) is False
    assert is_profile_complete(complete) is True


def test_build_therapy_plan_output():
    output = build_therapy_plan_output(
        {
            "selected_therapy_style": "cbt",
            "focus": "test",
            "themes": ["anxiety"],
            "timeline": "12 weeks",
            "initial_goals": ["Goal 1"],
            "current_progress": "Baseline established",
            "planned_interventions": ["Supportive listening"],
            "status": "active",
        }
    )

    assert output.selected_therapy_style == "cbt"
    assert output.focus == "test"
    assert output.themes == ["anxiety"]
