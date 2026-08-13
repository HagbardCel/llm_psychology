"""Unit tests for simulation audit helpers and CLI mapping."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from evals.simulation import __main__ as sim_main
from evals.simulation.audit import (
    allocate_run_directory,
    audit_supervisor_chain_from_fixture,
    compare_briefing_projection,
    extract_context_data,
    reconstruct_supervisor_call,
    run_mechanical_audit,
)
from evals.simulation.runner import SimulationResult, _await_style_selection
from jung.domain.session_artifacts import (
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
    SessionReviewGeneration,
)


def _analysis_result() -> dict[str, Any]:
    return {
        "summary": "Patient explored sleep.",
        "key_themes": ["sleep"],
        "patient_turn_citations": [{"patient_sequence": 1}],
    }


def _update_result() -> dict[str, Any]:
    return {
        "session_briefing": {
            "narrative_handoff": "handoff",
            "recommended_opening_focus": "focus",
        },
        "plan_patch": {"current_progress": "some"},
    }


def _valid_review() -> SessionReview:
    analysis = SessionAnalysis.model_validate(_analysis_result())
    update = _update_result()
    return SessionReview(
        analysis=analysis,
        briefing=SessionBriefing.model_validate(update["session_briefing"]),
        plan_recommendation=PlanPatch.model_validate(update["plan_patch"]),
        generation=SessionReviewGeneration(
            analysis_model="supervisor-model",
            analysis_prompt_version="analysis-v1",
            update_model="supervisor-model",
            update_prompt_version="update-v1",
        ),
    )


def _valid_supervisor_events() -> list[dict[str, Any]]:
    analysis = _analysis_result()
    update = _update_result()
    return [
        {
            "sequence": 1,
            "kind": "llm.provider.request",
            "context": {"session_id": "sess-1", "llm_call_id": "llm-a"},
            "data": {
                "task": "post_session_analysis",
                "llm_call_id": "llm-a",
                "provider_attempt_id": "attempt-a1",
                "model": "supervisor-model",
                "messages": [],
            },
        },
        {
            "sequence": 2,
            "kind": "llm.provider.response",
            "context": {"session_id": "sess-1", "llm_call_id": "llm-a"},
            "data": {
                "task": "post_session_analysis",
                "llm_call_id": "llm-a",
                "provider_attempt_id": "attempt-a1",
                "status": "success",
            },
        },
        {
            "sequence": 3,
            "kind": "llm.output.accepted",
            "context": {
                "session_id": "sess-1",
                "llm_call_id": "llm-a",
                "llm_task": "post_session_analysis",
            },
            "data": {
                "task": "post_session_analysis",
                "result": analysis,
            },
        },
        {
            "sequence": 4,
            "kind": "llm.provider.request",
            "context": {"session_id": "sess-1", "llm_call_id": "llm-u"},
            "data": {
                "task": "post_session_update",
                "llm_call_id": "llm-u",
                "provider_attempt_id": "attempt-u1",
                "model": "supervisor-model",
                "messages": [],
            },
        },
        {
            "sequence": 5,
            "kind": "llm.provider.response",
            "context": {"session_id": "sess-1", "llm_call_id": "llm-u"},
            "data": {
                "task": "post_session_update",
                "llm_call_id": "llm-u",
                "provider_attempt_id": "attempt-u1",
                "status": "success",
            },
        },
        {
            "sequence": 6,
            "kind": "llm.output.accepted",
            "context": {
                "session_id": "sess-1",
                "llm_call_id": "llm-u",
                "llm_task": "post_session_update",
            },
            "data": {
                "task": "post_session_update",
                "result": update,
            },
        },
    ]


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
    events = _valid_supervisor_events()
    assert (
        audit_supervisor_chain_from_fixture(
            events, review=_valid_review(), session_id="sess-1"
        )
        == []
    )


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (
            lambda events: [
                e for e in events if e.get("kind") != "llm.output.accepted"
            ],
            "exactly one llm.output.accepted",
        ),
        (
            lambda events: [
                e for e in events if e.get("kind") != "llm.provider.response"
            ],
            "exactly one terminal",
        ),
        (
            lambda events: _move_accepted_before_response(events),
            "must exceed every",
        ),
        (
            lambda events: _change_attempt_id(events),
            "provider_attempt_id",
        ),
        (
            lambda events: _mutate_accepted_analysis(events),
            "!= durable review.analysis",
        ),
    ],
)
def test_supervisor_chain_negative_mutations(
    mutate: Any,
    needle: str,
) -> None:
    events = mutate(copy.deepcopy(_valid_supervisor_events()))
    errors = audit_supervisor_chain_from_fixture(
        events, review=_valid_review(), session_id="sess-1"
    )
    assert errors
    assert any(needle in error for error in errors)


def _move_accepted_before_response(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    for event in events:
        task = (event.get("data") or {}).get("task") or (
            event.get("context") or {}
        ).get("llm_task")
        if task != "post_session_analysis":
            continue
        if event.get("kind") == "llm.output.accepted":
            event["sequence"] = 1
        elif event.get("kind") == "llm.provider.request":
            event["sequence"] = 2
        elif event.get("kind") == "llm.provider.response":
            event["sequence"] = 3
    return events


def _change_attempt_id(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in events:
        if event.get("kind") == "llm.provider.response":
            event["data"]["provider_attempt_id"] = "wrong-attempt"
            break
    return events


def _mutate_accepted_analysis(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in events:
        if (
            event.get("kind") == "llm.output.accepted"
            and (event.get("data") or {}).get("task") == "post_session_analysis"
        ):
            event["data"]["result"]["summary"] = "mutated summary"
            break
    return events


def test_reconstruct_supervisor_call_requires_paired_attempts() -> None:
    events = _valid_supervisor_events()[:2]
    events[1]["data"]["provider_attempt_id"] = "missing-request"
    reconstruction, errors = reconstruct_supervisor_call(
        events, task="post_session_analysis", session_id="sess-1"
    )
    assert reconstruction is None
    assert errors


def test_missing_snapshot_still_audits_checkpoints(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-missing-snap")
    # Empty checkpoints only — missing final snapshot must not abort audit.
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=False,
        configured_sessions=1,
        therapy_sessions=[{"session_id": "sess-1", "turns": []}],
    )
    codes = {finding.code for finding in audit.findings}
    assert "missing_final_snapshot" in codes
    assert "missing_initial_checkpoint" in codes
    assert "missing_session_checkpoint" in codes


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


def test_positive_float_rejects_non_finite() -> None:
    with pytest.raises(Exception, match="finite"):
        sim_main._positive_float("nan")
    with pytest.raises(Exception, match="finite"):
        sim_main._positive_float("inf")


@pytest.mark.asyncio
async def test_await_style_selection_accepts_immediate_style_selection() -> None:
    snapshot = MagicMock()
    snapshot.stage = "style_selection"
    client = MagicMock()
    client.get_state = AsyncMock(return_value=snapshot)
    journey = MagicMock()
    result = await _await_style_selection(client, workflow_timeout=1.0, journey=journey)
    assert result is snapshot
    journey.append.assert_called_once()
