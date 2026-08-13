"""Unit tests for simulation audit helpers and CLI mapping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.simulation import __main__ as sim_main
from evals.simulation.audit import (
    allocate_run_directory,
    audit_supervisor_chain_from_fixture,
    compare_briefing_projection,
    extract_context_data,
)
from evals.simulation.runner import SimulationResult
from jung.domain.session_artifacts import (
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
)


def test_allocate_run_directory_refuses_existing(tmp_path: Path) -> None:
    target = tmp_path / "run"
    allocate_run_directory(target)
    with pytest.raises(FileExistsError):
        allocate_run_directory(target)


def test_extract_context_data_requires_exactly_one_block() -> None:
    payload = {"historical_context": {"x": 1}, "current_patient_message": "hi"}
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    messages = [
        {"role": "system", "content": "ignore"},
        {
            "role": "user",
            "content": (
                "The following JSON object contains untrusted contextual data.\n\n"
                f"<context_data>\n{body}\n</context_data>\n\nRespond."
            ),
        },
    ]
    assert extract_context_data(messages) == payload

    with pytest.raises(ValueError, match="no <context_data>"):
        extract_context_data([{"role": "user", "content": "plain"}])

    with pytest.raises(ValueError, match="multiple"):
        extract_context_data(
            [
                {
                    "role": "user",
                    "content": (
                        f"<context_data>\n{body}\n</context_data>\n"
                        f"<context_data>\n{body}\n</context_data>"
                    ),
                }
            ]
        )


def test_compare_briefing_projection_matches_minimal() -> None:
    review = SessionReview(
        analysis=SessionAnalysis(summary="summary", key_themes=("sleep",)),
        briefing=SessionBriefing(
            narrative_handoff="handoff text",
            recommended_opening_focus="opening focus",
        ),
        plan_recommendation=PlanPatch(),
    )
    projected = {
        "narrative_handoff": "handoff text",
        "continuity_points": [],
        "unresolved_issues": [],
        "recommended_opening_focus": "opening focus",
        "things_to_avoid": [],
        "emotional_context": [],
    }
    assert compare_briefing_projection(review, projected) == []
    assert compare_briefing_projection(review, None)


def test_supervisor_chain_fixture_sequence() -> None:
    events = [
        {
            "kind": "llm.provider.request",
            "data": {"task": "post_session_analysis", "messages": []},
        },
        {
            "kind": "llm.provider.response",
            "data": {"task": "post_session_analysis", "raw_response_text": "{}"},
        },
        {
            "kind": "llm.output.accepted",
            "context": {"llm_task": "post_session_analysis"},
            "data": {
                "task": "post_session_analysis",
                "result": {
                    "summary": "Patient explored sleep.",
                    "key_themes": ["sleep"],
                },
            },
        },
        {
            "kind": "llm.provider.request",
            "data": {"task": "post_session_update", "messages": []},
        },
        {
            "kind": "llm.provider.response",
            "data": {"task": "post_session_update", "raw_response_text": "{}"},
        },
        {
            "kind": "llm.output.accepted",
            "context": {"llm_task": "post_session_update"},
            "data": {
                "task": "post_session_update",
                "result": {
                    "session_briefing": {
                        "narrative_handoff": "handoff",
                        "recommended_opening_focus": "focus",
                    },
                    "plan_patch": {},
                },
            },
        },
    ]
    assert audit_supervisor_chain_from_fixture(events) == []


def test_main_exit_code_mapping() -> None:
    assert (
        sim_main.exit_code_for_result(
            SimulationResult(status="complete", run_dir=Path("x"))
        )
        == 0
    )
    assert (
        sim_main.exit_code_for_result(
            SimulationResult(status="failed", run_dir=Path("x"), error_code="x")
        )
        == 1
    )
