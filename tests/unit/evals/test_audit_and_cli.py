"""Unit tests for simulation audit helpers and CLI mapping."""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from evals.simulation import __main__ as sim_main
from evals.simulation.audit import (
    AuditResult,
    JourneyLog,
    allocate_run_directory,
    audit_grounding,
    audit_supervisor_chain_from_fixture,
    compare_briefing_projection,
    extract_context_data,
    reconstruct_supervisor_call,
    run_mechanical_audit,
    write_private_text,
)
from evals.simulation.runner import (
    SimulationConfig,
    SimulationResult,
    _await_style_selection,
    _finalize_run,
)
from evals.simulation.scenarios import get_scenario
from jung.domain.session_artifacts import (
    PatientTurnCitation,
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
    SessionReviewGeneration,
)
from jung.persistence.sqlite_store import SQLiteStore


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
    ("mutate_events", "mutate_review", "needle"),
    [
        (
            lambda events: [
                e for e in events if e.get("kind") != "llm.output.accepted"
            ],
            None,
            "exactly one llm.output.accepted",
        ),
        (
            lambda events: [
                e for e in events if e.get("kind") != "llm.provider.response"
            ],
            None,
            "exactly one request and one terminal",
        ),
        (
            lambda events: _response_before_request(events),
            None,
            "request.sequence < terminal.sequence < accepted.sequence",
        ),
        (
            lambda events: _duplicate_attempt_id(events),
            None,
            "exactly one request and one terminal",
        ),
        (
            lambda events: _change_attempt_id(events),
            None,
            "provider_attempt_id",
        ),
        (
            lambda events: _wrong_llm_call_id(events),
            None,
            "exactly one llm_call_id",
        ),
        (
            lambda events: _blank_request_model(events),
            None,
            "non-empty model",
        ),
        (
            lambda events: _mutate_accepted_analysis(events),
            None,
            "!= durable review.analysis",
        ),
        (
            lambda events: _mutate_accepted_briefing(events),
            None,
            "session_briefing",
        ),
        (
            lambda events: _mutate_accepted_plan_patch(events),
            None,
            "plan_patch",
        ),
        (
            lambda events: events,
            lambda review: review.model_copy(
                update={
                    "generation": review.generation.model_copy(  # type: ignore[union-attr]
                        update={"analysis_model": "other-model"}
                    )
                }
            ),
            "analysis_model",
        ),
    ],
)
def test_supervisor_chain_negative_mutations(
    mutate_events: Any,
    mutate_review: Any,
    needle: str,
) -> None:
    events = mutate_events(copy.deepcopy(_valid_supervisor_events()))
    review = _valid_review()
    if mutate_review is not None:
        review = mutate_review(review)
    errors = audit_supervisor_chain_from_fixture(
        events, review=review, session_id="sess-1"
    )
    assert errors
    assert any(needle in error for error in errors)


def _response_before_request(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in events:
        task = (event.get("data") or {}).get("task") or (
            event.get("context") or {}
        ).get("llm_task")
        if task != "post_session_analysis":
            continue
        if event.get("kind") == "llm.provider.response":
            event["sequence"] = 1
        elif event.get("kind") == "llm.provider.request":
            event["sequence"] = 2
        elif event.get("kind") == "llm.output.accepted":
            event["sequence"] = 3
    return events


def _duplicate_attempt_id(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    duplicate = copy.deepcopy(events[0])
    duplicate["sequence"] = 10
    events.append(duplicate)
    return events


def _change_attempt_id(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in events:
        if event.get("kind") == "llm.provider.response":
            event["data"]["provider_attempt_id"] = "wrong-attempt"
            break
    return events


def _wrong_llm_call_id(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in events:
        if (
            event.get("kind") == "llm.output.accepted"
            and (event.get("data") or {}).get("task") == "post_session_analysis"
        ):
            event["data"]["llm_call_id"] = "wrong"
            event["context"]["llm_call_id"] = "wrong"
            break
    return events


def _blank_request_model(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events[0]["data"]["model"] = ""
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


def _mutate_accepted_briefing(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in events:
        if (
            event.get("kind") == "llm.output.accepted"
            and (event.get("data") or {}).get("task") == "post_session_update"
        ):
            event["data"]["result"]["session_briefing"]["narrative_handoff"] = (
                "mutated handoff"
            )
            break
    return events


def _mutate_accepted_plan_patch(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in events:
        if (
            event.get("kind") == "llm.output.accepted"
            and (event.get("data") or {}).get("task") == "post_session_update"
        ):
            event["data"]["result"]["plan_patch"]["current_progress"] = "mutated"
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


def test_malformed_trace_still_writes_terminal_artifacts(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-bad-trace")
    runtime = run_dir / "runtime"
    runtime.mkdir()
    write_private_text(runtime / "trace.jsonl", "{not-json\n")
    journey = JourneyLog(run_dir / "journey.jsonl")
    result = _finalize_run(
        config=SimulationConfig(
            scenario=get_scenario("anxiety_sleep"),
            sessions=1,
            turns_per_session=1,
        ),
        run_dir=run_dir,
        journey=journey,
        run_config={"scenario_id": "anxiety_sleep"},
        therapy_records=[],
        provider_trace_required=False,
        started_at="2020-01-01T00:00:00Z",
        journey_error=None,
        error_code=None,
        error_message=None,
    )
    assert result.status == "failed"
    assert result.error_code == "mechanical_audit_failed"
    audit_text = (run_dir / "audit.md").read_text(encoding="utf-8")
    assert "runtime_trace_read_failed" in audit_text
    assert (run_dir / "run.json").is_file()
    assert "simulation.failed" in (run_dir / "journey.jsonl").read_text(
        encoding="utf-8"
    )


def _minimal_grounding_conn(
    *,
    session_id: str,
    cite_sequence: int = 1,
    grounded: bool = False,
) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            review_json TEXT
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL
        );
        CREATE TABLE grounded_patient_turns (
            message_id TEXT PRIMARY KEY
        );
        """
    )
    review = SessionReview(
        analysis=SessionAnalysis(
            summary="summary",
            key_themes=("sleep",),
            patient_turn_citations=(
                PatientTurnCitation(patient_sequence=cite_sequence),
            ),
        ),
        briefing=SessionBriefing(
            narrative_handoff="handoff",
            recommended_opening_focus="focus",
        ),
        plan_recommendation=PlanPatch(),
    )
    message_id = "msg-1"
    conn.execute(
        "INSERT INTO sessions (id, kind, review_json) VALUES (?, 'therapy', ?)",
        (session_id, review.model_dump_json()),
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, sequence, role, content) "
        "VALUES (?, ?, ?, 'user', 'hello')",
        (message_id, session_id, cite_sequence),
    )
    if grounded:
        conn.execute(
            "INSERT INTO grounded_patient_turns (message_id) VALUES (?)",
            (message_id,),
        )
    conn.commit()
    return conn


def test_audit_grounding_set_mismatch_when_grounded_rows_missing() -> None:
    conn = _minimal_grounding_conn(session_id="sess-1", grounded=False)
    audit = AuditResult()
    try:
        audit_grounding(conn, audit)
    finally:
        conn.close()
    codes = {finding.code for finding in audit.findings}
    assert "grounding_set_mismatch" in codes


def _write_therapy_checkpoint_with_grounding_gap(
    path: Path,
    *,
    session_id: str,
) -> None:
    store = SQLiteStore(path)
    store.initialize()
    plan_id = str(uuid4())
    review = SessionReview(
        analysis=SessionAnalysis(
            summary="Patient explored sleep.",
            key_themes=("sleep",),
            patient_turn_citations=(PatientTurnCitation(patient_sequence=1),),
        ),
        briefing=SessionBriefing(
            narrative_handoff="handoff",
            recommended_opening_focus="focus",
        ),
        plan_recommendation=PlanPatch(),
        generation=SessionReviewGeneration(
            analysis_model="supervisor-model",
            analysis_prompt_version="analysis-v1",
            update_model="supervisor-model",
            update_prompt_version="update-v1",
        ),
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO plans (
                id, version, selected_style, focus, themes_json, goals_json,
                current_progress, planned_interventions_json,
                revision_recommendations_json, source_session_id,
                supersedes_plan_id, created_at
            ) VALUES (?, 1, 'style', 'focus', '[]', '[]', 'progress', '[]', '[]',
                      NULL, NULL, '2020-01-01T00:00:00Z')
            """,
            (plan_id,),
        )
        conn.execute(
            """
            INSERT INTO sessions (
                id, kind, plan_id, started_at, ended_at, review_json
            ) VALUES (?, 'therapy', ?, '2020-01-01T00:00:00Z',
                      '2020-01-01T01:00:00Z', ?)
            """,
            (session_id, plan_id, review.model_dump_json()),
        )
        conn.execute(
            """
            INSERT INTO messages (
                id, session_id, sequence, role, content, client_message_id,
                created_at
            ) VALUES (?, ?, 1, 'user', 'hello', ?, '2020-01-01T00:00:01Z')
            """,
            (str(uuid4()), session_id, str(uuid4())),
        )
        conn.execute(
            """
            UPDATE profile
            SET current_plan_id = ?, updated_at = '2020-01-01T00:00:00Z'
            WHERE singleton_id = 1
            """,
            (plan_id,),
        )
        conn.commit()
    finally:
        conn.close()


def test_newest_checkpoint_fallback_with_partial_later_session(
    tmp_path: Path,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-newest-checkpoint")
    session_1 = str(uuid4())
    session_2 = str(uuid4())
    _write_therapy_checkpoint_with_grounding_gap(
        run_dir / "checkpoints" / "after-session-001.sqlite",
        session_id=session_1,
    )
    runtime = run_dir / "runtime"
    runtime.mkdir()
    write_private_text(
        runtime / "trace.jsonl",
        json.dumps(
            {
                "sequence": 1,
                "kind": "llm.provider.request",
                "context": {"session_id": session_1},
                "data": {"task": "therapy_response", "messages": []},
            },
            separators=(",", ":"),
        )
        + "\n",
    )
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=2,
        therapy_sessions=[
            {"session_id": session_1, "turns": []},
            {"session_id": session_2, "turns": []},
        ],
    )
    codes = {finding.code for finding in audit.findings}
    assert "missing_final_snapshot" in codes
    assert "missing_session_checkpoint" in codes
    assert "grounding_set_mismatch" in codes
    assert "missing_analysis_request" in codes or "supervisor_chain" in codes


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
