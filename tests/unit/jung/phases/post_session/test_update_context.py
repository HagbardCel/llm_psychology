"""Post-session update context budgeting tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from jung.domain.models import Plan, Profile
from jung.phases.post_session.models import (
    PostSessionInput,
    SessionAnalysisResult,
)
from jung.phases.post_session.update_context import (
    _UPDATE_CONTEXT_LIMIT,
    _section_payload_budget,
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


def test_section_payload_budget_accounts_for_heading_prefix() -> None:
    heading = "Session analysis"
    remaining = 100
    budget = _section_payload_budget(heading, remaining, remaining)
    assert budget == remaining - len(f"{heading}:\n")


def test_builder_rendered_output_never_exceeds_update_context_limit() -> None:
    sections = build_update_context_sections(
        _input(
            prior_session_briefing={"summary": "b" * 5000},
            recent_session_summaries=tuple(f"summary-{index}" * 200 for index in range(20)),
            derived_profile={"observations": ["p" * 5000]},
        ),
        SessionAnalysisResult(
            summary="x" * 5000,
            key_themes=tuple(f"theme-{index}" for index in range(50)),
        ),
    )
    rendered = "\n\n".join(sections)
    assert len(rendered) <= _UPDATE_CONTEXT_LIMIT


def test_optional_sections_drop_before_plan_categories() -> None:
    style = replace(load_styles()["cbt"], post_session_instructions="s" * 5000)
    sections = build_update_context_sections(
        _input(
            selected_style=style,
            prior_session_briefing={"summary": "OPTIONAL_BRIEFING_MARKER" * 2000},
            recent_session_summaries=("old " * 2000, "new " * 2000),
            derived_profile={"observations": ["p" * 5000]},
        ),
        SessionAnalysisResult(
            summary="x" * 10000,
            key_themes=tuple(f"theme-{index}" * 20 for index in range(80)),
        ),
    )
    rendered = "\n\n".join(sections)
    assert len(rendered) <= _UPDATE_CONTEXT_LIMIT
    assert not any(
        section.startswith("Recent session summaries:") for section in sections
    )
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
        _input(
            recent_session_summaries=(
                "old summary",
                "middle-too-large " * 400,
                "newest summary",
            )
        ),
        _analysis(),
    )
    summary_section = next(
        section for section in sections if section.startswith("Recent session summaries:")
    )
    body = summary_section.split(":\n", 1)[1]
    assert body == "newest summary"
    assert "old summary" not in body
    assert "middle-too-large" not in body


def test_serialized_sections_are_valid_json_or_prose() -> None:
    sections = build_update_context_sections(_input(), _analysis())
    for section in sections:
        if section.startswith("Session analysis:"):
            json.loads(section.split(":\n", 1)[1])
        if section.startswith("Current plan:") or section.startswith("Derived profile:"):
            json.loads(section.split(":\n", 1)[1])
        if section.startswith("Prior session briefing:"):
            assert not section.split(":\n", 1)[1].startswith("{")
