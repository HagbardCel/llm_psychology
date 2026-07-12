"""Post-session update context budgeting tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from jung.domain.models import Plan, Profile
from jung.phases.post_session.models import (
    PostSessionInput,
    SessionAnalysisResult,
)
from jung.phases.post_session.update_context import (
    _UPDATE_CONTEXT_LIMIT,
    build_update_context_sections,
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
        themes=["worry", "sleep"],
        goals=["sleep better", "reduce worry"],
        current_progress="baseline",
        planned_interventions=["grounding", "thought record"],
        revision_recommendations=["review goals"],
        created_at=now,
    )


def _input(**overrides: object) -> PostSessionInput:
    style = load_styles()["cbt"]
    values: dict[str, object] = {
        "transcript": (
            TranscriptTurn(
                message_id=uuid4(),
                sequence=1,
                role="user",
                content="I slept badly.",
            ),
        ),
        "current_plan": _plan(),
        "profile": Profile(name="Alex", primary_language="English"),
        "selected_style": style,
    }
    values.update(overrides)
    return PostSessionInput(**values)


def _analysis() -> SessionAnalysisResult:
    return SessionAnalysisResult(
        summary="Sleep difficulties explored.",
        key_themes=("sleep", "worry"),
    )


def test_update_context_stays_within_total_budget() -> None:
    sections = build_update_context_sections(_input(), _analysis())
    rendered = "\n\n".join(sections)
    assert rendered
    assert len(rendered) <= _UPDATE_CONTEXT_LIMIT


def test_optional_sections_drop_before_plan_categories() -> None:
    marker = "OPTIONAL_BRIEFING_MARKER"
    sections = build_update_context_sections(
        _input(
            prior_session_briefing={"summary": marker * 200},
            recent_session_summaries=("old " * 1000, "new " * 1000),
            derived_profile={"observations": ["p" * 2000]},
        ),
        SessionAnalysisResult(
            summary="x" * 3000,
            key_themes=tuple(f"theme-{index}" for index in range(50)),
        ),
    )
    rendered = "\n\n".join(sections)
    assert len(rendered) <= _UPDATE_CONTEXT_LIMIT
    plan_section = next(section for section in sections if section.startswith("Current plan:"))
    document = json.loads(plan_section.split(":\n", 1)[1])
    assert set(document) == {
        "focus",
        "themes",
        "goals",
        "current_progress",
        "planned_interventions",
        "revision_recommendations",
    }


def test_plan_section_retains_all_semantic_field_names() -> None:
    sections = build_update_context_sections(_input(), _analysis())
    plan_section = next(section for section in sections if section.startswith("Current plan:"))
    payload = plan_section.split(":\n", 1)[1]
    document = json.loads(payload)
    assert set(document) == {
        "focus",
        "themes",
        "goals",
        "current_progress",
        "planned_interventions",
        "revision_recommendations",
    }
    assert document["goals"]
    assert document["planned_interventions"]


def test_newest_summaries_preferred() -> None:
    sections = build_update_context_sections(
        _input(recent_session_summaries=("older summary", "newer summary")),
        _analysis(),
    )
    rendered = "\n\n".join(sections)
    if "Recent session summaries" in rendered:
        assert rendered.rfind("newer summary") > rendered.rfind("older summary")


def test_serialized_sections_are_valid_json_or_prose() -> None:
    sections = build_update_context_sections(_input(), _analysis())
    for section in sections:
        if section.startswith("Current plan:") or section.startswith("Derived profile:"):
            json.loads(section.split(":\n", 1)[1])
        if section.startswith("Prior session briefing:"):
            assert not section.split(":\n", 1)[1].startswith("{")
