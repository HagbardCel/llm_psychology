"""Post-session nested model strictness tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.models import Plan, Profile
from jung.phases.post_session.models import (
    InterventionEvidence,
    PostSessionInput,
    PostSessionResult,
    SessionBriefing,
)
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles


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


def test_post_session_input_rejects_mismatched_style() -> None:
    with pytest.raises(ValidationError, match="selected_style must match"):
        PostSessionInput(
            transcript=(
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=1,
                    role="user",
                    content="I slept badly.",
                ),
            ),
            current_plan=_plan(),
            profile=Profile(name="Alex", primary_language="English"),
            selected_style=load_styles()["jung"],
        )


@pytest.mark.parametrize(
    ("payload", "expected_loc"),
    [
        (
            {
                "intervention": "breathing",
                "status": "proposed",
                "unexpected": "field",
            },
            ("unexpected",),
        ),
        (
            {
                "intervention": "   ",
                "status": "proposed",
            },
            ("intervention",),
        ),
        (
            {
                "narrative_handoff": "   ",
                "recommended_opening_focus": "sleep",
            },
            ("narrative_handoff",),
        ),
        (
            {
                "narrative_handoff": "handoff",
                "recommended_opening_focus": "   ",
            },
            ("recommended_opening_focus",),
        ),
        (
            {"session_summary": "   "},
            ("session_summary",),
        ),
    ],
)
def test_post_session_models_reject_invalid_fields(
    payload: dict[str, object],
    expected_loc: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        if "session_summary" in payload:
            PostSessionResult.model_validate(
                {
                    "session_summary": payload["session_summary"],
                    "session_briefing": {
                        "narrative_handoff": "handoff",
                        "recommended_opening_focus": "sleep",
                    },
                    "derived_profile_patch": {},
                    "plan_patch": {},
                }
            )
        elif "narrative_handoff" in payload or "recommended_opening_focus" in payload:
            SessionBriefing.model_validate(payload)
        else:
            InterventionEvidence.model_validate(payload)
    assert expected_loc[0] in {error["loc"][-1] for error in exc_info.value.errors()}
