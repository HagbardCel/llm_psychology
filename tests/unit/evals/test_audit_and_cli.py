"""Unit tests for simulation audit helpers and CLI mapping."""

from __future__ import annotations

import copy
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from evals.simulation import __main__ as sim_main
from evals.simulation import audit as audit_mod
from evals.simulation.audit import (
    AuditFinding,
    AuditResult,
    JourneyLog,
    allocate_run_directory,
    artifact_relative_paths,
    audit_grounding,
    audit_supervisor_chain_from_fixture,
    compare_briefing_projection,
    extract_context_data,
    format_diagnostic_capture_status,
    reconstruct_structured_call,
    render_audit_markdown,
    run_mechanical_audit,
    write_private_text,
)
from evals.simulation.runner import (
    SimulationConfig,
    SimulationError,
    SimulationProgress,
    SimulationResult,
    _await_style_selection,
    _finalize_run,
    _select_initial_style,
    collect_chat_completion,
    initial_style_selection_metadata,
    resolve_style_selection,
    style_selection_mode,
)
from evals.simulation.scenarios import get_scenario
from jung.api.contracts import (
    ErrorEnvelope,
    ErrorEvent,
    MessageCompletedEvent,
    MessageFailedEvent,
    MessageResponse,
    TokenEvent,
)
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


def test_allocate_run_directory_retries_forced_suffix_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(audit_mod, "_allocation_stamp", lambda: "20260817T113412Z")
    suffixes = iter(("deadbeef", "deadbeef", "cafebabe"))
    monkeypatch.setattr(audit_mod, "_allocation_suffix", lambda: next(suffixes))

    first = allocate_run_directory()
    second = allocate_run_directory()
    assert first.name == "run-20260817T113412Z-deadbeef"
    assert second.name == "run-20260817T113412Z-cafebabe"
    assert first.is_dir()
    assert second.is_dir()
    assert (first / "data").is_dir()
    assert (second / "checkpoints").is_dir()


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


def test_reconstruct_structured_call_requires_paired_attempts() -> None:
    events = _valid_supervisor_events()[:2]
    events[1]["data"]["provider_attempt_id"] = "missing-request"
    reconstruction, errors = reconstruct_structured_call(
        events, task="post_session_analysis", session_id="sess-1"
    )
    assert reconstruction is None
    assert errors


def test_reconstruct_rejects_extra_attempt_missing_llm_call_id() -> None:
    events = copy.deepcopy(_valid_supervisor_events())
    events.extend(
        [
            {
                "sequence": 100,
                "kind": "llm.provider.request",
                "context": {"session_id": "sess-1"},
                "data": {
                    "task": "post_session_analysis",
                    "provider_attempt_id": "orphan-extra",
                    "model": "supervisor-model",
                    "messages": [],
                },
            },
            {
                "sequence": 101,
                "kind": "llm.provider.response",
                "context": {"session_id": "sess-1"},
                "data": {
                    "task": "post_session_analysis",
                    "provider_attempt_id": "orphan-extra",
                    "status": "success",
                },
            },
        ]
    )
    reconstruction, errors = reconstruct_structured_call(
        events, task="post_session_analysis", session_id="sess-1"
    )
    assert reconstruction is None
    assert any("missing llm_call_id" in error for error in errors)


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
        run_config={
            "scenario_id": "anxiety_sleep",
            "patient_model": "test-model",
            "patient_endpoint": "http://127.0.0.1:8000/v1",
            "patient_extra_body": None,
        },
        therapy_records=[],
        progress=SimulationProgress(),
        provider_trace_required=False,
        started_at="2020-01-01T00:00:00Z",
        journey_error=None,
        error_code=None,
        error_message=None,
        api_error=None,
    )
    assert result.status == "failed"
    assert result.error_code == "mechanical_audit_failed"
    audit_text = (run_dir / "audit.md").read_text(encoding="utf-8")
    assert "runtime_trace_read_failed" in audit_text
    assert (run_dir / "run.json").is_file()
    assert "simulation.failed" in (run_dir / "journey.jsonl").read_text(
        encoding="utf-8"
    )


def test_audit_md_write_failure_sets_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-audit-write-clean")
    journey = JourneyLog(run_dir / "journey.jsonl")
    monkeypatch.setattr(
        "evals.simulation.runner.run_mechanical_audit",
        lambda **_kwargs: AuditResult(),
    )
    real_write = write_private_text

    def boom(path: Path, text: str) -> None:
        if path.name == "audit.md":
            raise OSError("simulated audit write failure")
        real_write(path, text)

    monkeypatch.setattr("evals.simulation.runner.write_private_text", boom)
    result = _finalize_run(
        config=SimulationConfig(
            scenario=get_scenario("anxiety_sleep"),
            sessions=1,
            turns_per_session=1,
        ),
        run_dir=run_dir,
        journey=journey,
        run_config={
            "scenario_id": "anxiety_sleep",
            "patient_model": "test-model",
            "patient_endpoint": "http://127.0.0.1:8000/v1",
            "patient_extra_body": None,
        },
        therapy_records=[],
        progress=SimulationProgress(),
        provider_trace_required=False,
        started_at="2020-01-01T00:00:00Z",
        journey_error=None,
        error_code=None,
        error_message=None,
        api_error=None,
    )
    assert result.status == "failed"
    assert result.error_code == "audit_write_failed"
    assert result.error_message
    run_payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_payload["status"] == "failed"
    assert run_payload["error_code"] == "audit_write_failed"
    assert run_payload["error_message"]
    terminal = [
        json.loads(line)
        for line in (run_dir / "journey.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][-1]
    assert terminal["kind"] == "simulation.failed"
    assert "audit_write_failed" in terminal["data"]["finding_codes"]


def test_audit_md_write_failure_preserves_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-audit-write-preserve")
    journey = JourneyLog(run_dir / "journey.jsonl")
    monkeypatch.setattr(
        "evals.simulation.runner.run_mechanical_audit",
        lambda **_kwargs: AuditResult(),
    )
    real_write = write_private_text

    def boom(path: Path, text: str) -> None:
        if path.name == "audit.md":
            raise OSError("simulated audit write failure")
        real_write(path, text)

    monkeypatch.setattr("evals.simulation.runner.write_private_text", boom)
    result = _finalize_run(
        config=SimulationConfig(
            scenario=get_scenario("anxiety_sleep"),
            sessions=1,
            turns_per_session=1,
        ),
        run_dir=run_dir,
        journey=journey,
        run_config={
            "scenario_id": "anxiety_sleep",
            "patient_model": "test-model",
            "patient_endpoint": "http://127.0.0.1:8000/v1",
            "patient_extra_body": None,
        },
        therapy_records=[],
        progress=SimulationProgress(),
        provider_trace_required=False,
        started_at="2020-01-01T00:00:00Z",
        journey_error=None,
        error_code="chat_invalid_llm_output",
        error_message="bad model output",
        api_error=None,
    )
    assert result.status == "failed"
    assert result.error_code == "chat_invalid_llm_output"
    assert result.error_message == "bad model output"
    terminal = [
        json.loads(line)
        for line in (run_dir / "journey.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][-1]
    assert terminal["kind"] == "simulation.failed"
    assert terminal["data"]["error_code"] == "chat_invalid_llm_output"
    assert "audit_write_failed" in terminal["data"]["finding_codes"]


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
        "".join(
            json.dumps(event, separators=(",", ":")) + "\n"
            for event in (
                {
                    "sequence": 1,
                    "kind": "llm.call.started",
                    "context": {"session_id": session_1},
                    "data": {},
                },
                {
                    "sequence": 2,
                    "kind": "llm.provider.request",
                    "context": {"session_id": session_1},
                    "data": {"task": "therapy_response", "messages": []},
                },
            )
        ),
    )
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=2,
        initial_ready_reached=True,
        therapy_sessions=[
            {"session_id": session_1, "post_session_entered": True, "turns": []},
            {"session_id": session_2, "post_session_entered": False, "turns": []},
        ],
    )
    codes = {finding.code for finding in audit.findings}
    assert "missing_initial_checkpoint" in codes
    assert "missing_final_snapshot" in codes
    assert "grounding_set_mismatch" in codes
    assert "missing_analysis_request" in codes or "supervisor_chain" in codes
    assert "missing_session_checkpoint" not in codes


def test_mechanical_audit_initial_ready_not_reached_is_not_applicable(
    tmp_path: Path,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-no-ready")
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=False,
        configured_sessions=0,
        initial_ready_reached=False,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    na_codes = {item.code for item in audit.not_applicable}
    assert "missing_initial_checkpoint" not in codes
    assert "initial_ready_checkpoint" in na_codes


def test_mechanical_audit_initial_ready_without_checkpoint_fails(
    tmp_path: Path,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-ready-no-checkpoint")
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=False,
        configured_sessions=0,
        initial_ready_reached=True,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert "missing_initial_checkpoint" in codes


def test_format_diagnostic_capture_status() -> None:
    assert format_diagnostic_capture_status("success") == "COMPLETE"
    assert format_diagnostic_capture_status("failed") == "FAILED"
    assert format_diagnostic_capture_status(None) == "UNKNOWN"


def test_render_audit_markdown_includes_not_applicable_and_dirty_warning() -> None:
    text = render_audit_markdown(
        status="failed",
        runtime_diagnostics_status="success",
        findings=[],
        warnings=[],
        not_applicable=[
            AuditFinding(
                code="initial_ready_checkpoint",
                message="run never reached READY",
            )
        ],
        run_config={
            "git_worktree_dirty": True,
            "scenario_id": "anxiety_sleep",
            "style_selection": {
                "mode": "explicit",
                "requested_style": "jung",
                "recommendations": [],
                "selected_style_id": None,
            },
        },
        artifact_index=["run.json"],
        journey_error_code="chat_invalid_llm_output",
        journey_error_message="The language model returned an invalid response.",
        journey_api_error={
            "code": "invalid_llm_output",
            "message": "The language model returned an invalid response.",
            "retryable": None,
            "event_type": "message_failed",
        },
    )
    assert "Diagnostic capture: COMPLETE" in text
    assert "WARNING: source worktree was dirty" in text
    assert "Style selection: mode=explicit, requested='jung', selected=None" in text
    assert "## Not applicable" in text
    assert "initial_ready_checkpoint" in text
    assert "invalid_llm_output" in text


@pytest.mark.asyncio
async def test_collect_chat_completion_message_failed_preserves_api_error() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    failed = MessageFailedEvent(
        type="message_failed",
        request_id=request_id,
        session_id=session_id,
        client_message_id=client_message_id,
        error=ErrorEnvelope(
            code="invalid_llm_output",
            message="The language model returned an invalid response.",
            request_id=request_id,
            retryable=None,
        ),
    )

    @asynccontextmanager
    async def stream_message(*_args: Any, **_kwargs: Any) -> Any:
        async def events() -> Any:
            yield failed

        yield events()

    client = MagicMock()
    client.stream_message = stream_message

    with pytest.raises(SimulationError) as exc_info:
        await collect_chat_completion(
            client,
            session_id=session_id,
            content="hello",
            client_message_id=client_message_id,
            request_id=request_id,
        )
    assert exc_info.value.code == "chat_invalid_llm_output"
    assert exc_info.value.details["retryable"] is None
    assert exc_info.value.details["event_type"] == "message_failed"


@pytest.mark.asyncio
async def test_collect_chat_completion_error_event_preserves_api_error() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    error_event = ErrorEvent(
        type="error",
        request_id=request_id,
        session_id=session_id,
        client_message_id=client_message_id,
        error=ErrorEnvelope(
            code="validation_error",
            message="bad request",
            request_id=request_id,
            retryable=False,
        ),
    )

    @asynccontextmanager
    async def stream_message(*_args: Any, **_kwargs: Any) -> Any:
        async def events() -> Any:
            yield error_event

        yield events()

    client = MagicMock()
    client.stream_message = stream_message

    with pytest.raises(SimulationError) as exc_info:
        await collect_chat_completion(
            client,
            session_id=session_id,
            content="hello",
            client_message_id=client_message_id,
            request_id=request_id,
        )
    assert exc_info.value.code == "chat_validation_error"
    assert exc_info.value.details["retryable"] is False
    assert exc_info.value.details["event_type"] == "error"


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


def test_parser_style_defaults_to_auto_and_accepts_catalog() -> None:
    parser = sim_main.build_parser()
    args = parser.parse_args(
        ["--scenario", "anxiety_sleep", "--sessions", "1", "--turns-per-session", "1"]
    )
    assert args.style == "auto"
    from jung.styles import load_styles

    style_ids = set(load_styles())
    for style_id in style_ids:
        parsed = parser.parse_args(
            [
                "--scenario",
                "anxiety_sleep",
                "--sessions",
                "1",
                "--turns-per-session",
                "1",
                "--style",
                style_id,
            ]
        )
        assert parsed.style == style_id
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--scenario",
                "anxiety_sleep",
                "--sessions",
                "1",
                "--turns-per-session",
                "1",
                "--style",
                "not-a-style",
            ]
        )


def test_style_selection_mode_and_initial_metadata() -> None:
    assert style_selection_mode(None) == "assessment_top"
    assert style_selection_mode("jung") == "explicit"
    auto = initial_style_selection_metadata(None)
    assert auto == {
        "mode": "assessment_top",
        "requested_style": None,
        "recommendations": [],
        "selected_style_id": None,
    }
    explicit = initial_style_selection_metadata("cbt")
    assert explicit["mode"] == "explicit"
    assert explicit["requested_style"] == "cbt"
    assert explicit["selected_style_id"] is None


def test_resolve_style_selection_auto_and_explicit() -> None:
    recommendations = [
        MagicMock(style_id="jung", score=0.5),
        MagicMock(style_id="cbt", score=0.9),
        MagicMock(style_id="freud", score=0.5),
    ]
    assert resolve_style_selection(recommendations, requested_style=None).style_id == (
        "cbt"
    )
    assert (
        resolve_style_selection(recommendations, requested_style="jung").style_id
        == "jung"
    )
    with pytest.raises(SimulationError) as exc_info:
        resolve_style_selection(recommendations, requested_style="missing")
    assert exc_info.value.code == "style_selection"
    assert "missing" in exc_info.value.message
    with pytest.raises(SimulationError) as exc_info:
        resolve_style_selection([], requested_style=None)
    assert exc_info.value.code == "style_selection"


@pytest.mark.asyncio
async def test_select_initial_style_records_recommendations_before_put_failure(
    tmp_path: Path,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "style-put-fail")
    (run_dir / "data").mkdir(exist_ok=True)
    journey = JourneyLog(run_dir / "journey.jsonl")
    recommendation = MagicMock(
        style_id="jung",
        score=0.4,
        rationale="depth",
        key_topics=["dreams"],
    )
    styles = MagicMock()
    styles.recommendations = [
        MagicMock(
            style_id="cbt",
            score=0.9,
            rationale="skills",
            key_topics=["anxiety"],
        ),
        recommendation,
    ]
    client = MagicMock()
    client.get_styles = AsyncMock(return_value=styles)
    client.select_style = AsyncMock(
        side_effect=SimulationError("style_selection", "put failed")
    )
    config = SimulationConfig(
        scenario=get_scenario("anxiety_sleep"),
        sessions=1,
        turns_per_session=1,
        requested_style="jung",
        workflow_timeout=1.0,
    )
    isolated = MagicMock()
    isolated.database_path = run_dir / "data" / "jung.sqlite"
    isolated.data_dir = run_dir / "data"
    style_selection_out = {
        "style_selection": initial_style_selection_metadata("jung"),
    }
    with pytest.raises(SimulationError, match="put failed"):
        await _select_initial_style(
            client=client,
            config=config,
            journey=journey,
            isolated=isolated,
            progress=SimulationProgress(),
            style_selection_out=style_selection_out,
        )
    selection = style_selection_out["style_selection"]
    assert selection["mode"] == "explicit"
    assert selection["requested_style"] == "jung"
    assert selection["selected_style_id"] is None
    assert [item["style_id"] for item in selection["recommendations"]] == [
        "cbt",
        "jung",
    ]
    journey_text = (run_dir / "journey.jsonl").read_text(encoding="utf-8")
    assert "style.selected" not in journey_text


@pytest.mark.asyncio
async def test_select_initial_style_emits_selected_after_ready_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "style-ok")
    (run_dir / "data").mkdir(exist_ok=True)
    (run_dir / "checkpoints").mkdir(exist_ok=True)
    journey = JourneyLog(run_dir / "journey.jsonl")
    selected = MagicMock(
        style_id="jung",
        score=0.4,
        rationale="depth",
        key_topics=["dreams"],
    )
    styles = MagicMock()
    styles.recommendations = [
        MagicMock(
            style_id="cbt",
            score=0.9,
            rationale="skills",
            key_topics=["anxiety"],
        ),
        selected,
    ]
    immediate = MagicMock()
    immediate.stage = "style_selection"
    immediate.selected_style = None
    ready = MagicMock()
    ready.stage = "ready"
    ready.selected_style = "jung"
    client = MagicMock()
    client.get_styles = AsyncMock(return_value=styles)
    client.select_style = AsyncMock(return_value=immediate)
    client.get_state = AsyncMock(return_value=ready)
    monkeypatch.setattr(
        "evals.simulation.runner.create_checkpoint",
        lambda *_args, **_kwargs: None,
    )
    config = SimulationConfig(
        scenario=get_scenario("anxiety_sleep"),
        sessions=1,
        turns_per_session=1,
        requested_style="jung",
        workflow_timeout=1.0,
    )
    isolated = MagicMock()
    isolated.database_path = run_dir / "data" / "jung.sqlite"
    isolated.data_dir = run_dir / "data"
    style_selection_out = {
        "style_selection": initial_style_selection_metadata("jung"),
    }
    progress = SimulationProgress()
    await _select_initial_style(
        client=client,
        config=config,
        journey=journey,
        isolated=isolated,
        progress=progress,
        style_selection_out=style_selection_out,
    )
    assert style_selection_out["style_selection"]["selected_style_id"] == "jung"
    assert progress.initial_ready_reached is True
    events = [
        json.loads(line)
        for line in (run_dir / "journey.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected_events = [event for event in events if event["kind"] == "style.selected"]
    assert len(selected_events) == 1
    assert selected_events[0]["data"]["mode"] == "explicit"
    assert selected_events[0]["data"]["requested_style"] == "jung"
    assert selected_events[0]["data"]["selected_style_id"] == "jung"


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


def _message_response(
    *,
    session_id: UUID,
    client_message_id: UUID,
    role: str,
    content: str,
    sequence: int,
) -> MessageResponse:
    return MessageResponse(
        id=uuid4(),
        session_id=session_id,
        sequence=sequence,
        role=role,  # type: ignore[arg-type]
        content=content,
        created_at=datetime.now(UTC),
        client_message_id=client_message_id,
    )


def _stream_client(events: list[Any]) -> MagicMock:
    @asynccontextmanager
    async def stream_message(*_args: Any, **_kwargs: Any) -> Any:
        async def iterator() -> Any:
            for event in events:
                yield event

        yield iterator()

    client = MagicMock()
    client.stream_message = stream_message
    return client


@pytest.mark.asyncio
async def test_collect_chat_completion_unknown_event_has_no_api_error() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    client = _stream_client(
        [
            TokenEvent(
                type="token",
                text="x",
                request_id=request_id,
                session_id=session_id,
                client_message_id=client_message_id,
            ),
            object(),
        ]
    )
    with pytest.raises(SimulationError) as exc_info:
        await collect_chat_completion(
            client,
            session_id=session_id,
            content="hello",
            client_message_id=client_message_id,
            request_id=request_id,
        )
    assert exc_info.value.code == "chat_terminal_failure"
    assert exc_info.value.details == {}


@pytest.mark.asyncio
async def test_collect_chat_completion_eof_has_no_api_error() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    client = _stream_client([])
    with pytest.raises(SimulationError) as exc_info:
        await collect_chat_completion(
            client,
            session_id=session_id,
            content="hello",
            client_message_id=client_message_id,
            request_id=request_id,
        )
    assert exc_info.value.code == "chat_terminal_failure"
    assert exc_info.value.details == {}


@pytest.mark.asyncio
async def test_collect_chat_completion_stream_text_mismatch() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    completed = MessageCompletedEvent(
        type="message_completed",
        request_id=request_id,
        session_id=session_id,
        client_message_id=client_message_id,
        user_message=_message_response(
            session_id=session_id,
            client_message_id=client_message_id,
            role="user",
            content="hello",
            sequence=1,
        ),
        assistant_message=_message_response(
            session_id=session_id,
            client_message_id=client_message_id,
            role="assistant",
            content="reply",
            sequence=2,
        ),
    )
    client = _stream_client(
        [
            TokenEvent(
                type="token",
                text="other",
                request_id=request_id,
                session_id=session_id,
                client_message_id=client_message_id,
            ),
            completed,
        ]
    )
    with pytest.raises(SimulationError) as exc_info:
        await collect_chat_completion(
            client,
            session_id=session_id,
            content="hello",
            client_message_id=client_message_id,
            request_id=request_id,
        )
    assert exc_info.value.code == "stream_persistence_mismatch"
    assert exc_info.value.details == {}


@pytest.mark.asyncio
async def test_collect_chat_completion_submitted_text_mismatch() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    completed = MessageCompletedEvent(
        type="message_completed",
        request_id=request_id,
        session_id=session_id,
        client_message_id=client_message_id,
        user_message=_message_response(
            session_id=session_id,
            client_message_id=client_message_id,
            role="user",
            content="stored",
            sequence=1,
        ),
        assistant_message=_message_response(
            session_id=session_id,
            client_message_id=client_message_id,
            role="assistant",
            content="reply",
            sequence=2,
        ),
    )
    client = _stream_client(
        [
            TokenEvent(
                type="token",
                text="reply",
                request_id=request_id,
                session_id=session_id,
                client_message_id=client_message_id,
            ),
            completed,
        ]
    )
    with pytest.raises(SimulationError) as exc_info:
        await collect_chat_completion(
            client,
            session_id=session_id,
            content="hello",
            client_message_id=client_message_id,
            request_id=request_id,
        )
    assert exc_info.value.code == "stream_persistence_mismatch"
    assert exc_info.value.details == {}


@pytest.mark.asyncio
async def test_collect_chat_completion_success() -> None:
    session_id = uuid4()
    client_message_id = uuid4()
    request_id = uuid4()
    completed = MessageCompletedEvent(
        type="message_completed",
        request_id=request_id,
        session_id=session_id,
        client_message_id=client_message_id,
        user_message=_message_response(
            session_id=session_id,
            client_message_id=client_message_id,
            role="user",
            content="hello",
            sequence=1,
        ),
        assistant_message=_message_response(
            session_id=session_id,
            client_message_id=client_message_id,
            role="assistant",
            content="reply",
            sequence=2,
        ),
    )
    client = _stream_client(
        [
            TokenEvent(
                type="token",
                text="re",
                request_id=request_id,
                session_id=session_id,
                client_message_id=client_message_id,
            ),
            TokenEvent(
                type="token",
                text="ply",
                request_id=request_id,
                session_id=session_id,
                client_message_id=client_message_id,
            ),
            completed,
        ]
    )
    turn = await collect_chat_completion(
        client,
        session_id=session_id,
        content="hello",
        client_message_id=client_message_id,
        request_id=request_id,
    )
    assert turn.patient_text == "hello"
    assert turn.assistant_text == "reply"
    assert turn.client_message_id == client_message_id


def _write_trace(run_dir: Path, events: list[dict[str, Any]]) -> None:
    runtime = run_dir / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    write_private_text(
        runtime / "trace.jsonl",
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
    )


def test_provider_trace_required_no_started_is_not_applicable(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-provider-na")
    _write_trace(run_dir, [])
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=0,
        initial_ready_reached=False,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    na_codes = {item.code for item in audit.not_applicable}
    assert "missing_provider_trace" not in codes
    assert "missing_llm_call_started" not in codes
    assert "provider_trace" in na_codes


def test_provider_trace_required_missing_trace_file_fails(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-provider-missing-file")
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=0,
        initial_ready_reached=False,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert "missing_provider_trace" in codes


def test_provider_trace_required_empty_trace_with_progress_fails(
    tmp_path: Path,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-provider-empty-progress")
    _write_trace(run_dir, [])
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=0,
        initial_ready_reached=True,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert "missing_provider_trace" in codes


def test_provider_trace_required_started_without_request_fails(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-provider-missing")
    _write_trace(
        run_dir,
        [{"sequence": 1, "kind": "llm.call.started", "context": {}, "data": {}}],
    )
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=0,
        initial_ready_reached=False,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert "missing_provider_trace" in codes


def test_provider_trace_required_request_without_started_fails(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-provider-orphan")
    _write_trace(
        run_dir,
        [
            {
                "sequence": 1,
                "kind": "llm.provider.request",
                "context": {},
                "data": {"task": "therapy_response", "messages": []},
            }
        ],
    )
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=0,
        initial_ready_reached=False,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert "missing_llm_call_started" in codes
    assert "missing_provider_trace" not in codes


def test_provider_trace_required_both_present_runs_chains(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-provider-both")
    session_id = str(uuid4())
    _write_trace(
        run_dir,
        [
            {"sequence": 1, "kind": "llm.call.started", "context": {}, "data": {}},
            {
                "sequence": 2,
                "kind": "llm.provider.request",
                "context": {"session_id": session_id},
                "data": {"task": "therapy_response", "messages": []},
            },
        ],
    )
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=1,
        initial_ready_reached=False,
        therapy_sessions=[
            {"session_id": session_id, "post_session_entered": False, "turns": []}
        ],
    )
    codes = {finding.code for finding in audit.findings}
    assert "missing_provider_trace" not in codes
    assert "missing_llm_call_started" not in codes
    assert "assessment_chain" in codes
    na_codes = {item.code for item in audit.not_applicable}
    assert "supervisor_chain" in na_codes


_PRETHERAPY_CODES = {
    "missing_intake_response",
    "intake_patch_chain",
    "assessment_chain",
}


def _structured_call_events(
    *,
    task: str,
    session_id: str,
    client_message_id: str | None,
    llm_call_id: str,
    attempt_id: str,
    sequence_start: int,
    result: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context: dict[str, Any] = {
        "session_id": session_id,
        "llm_call_id": llm_call_id,
    }
    if client_message_id is not None:
        context["client_message_id"] = client_message_id
    return [
        {
            "sequence": sequence_start,
            "kind": "llm.provider.request",
            "context": dict(context),
            "data": {
                "task": task,
                "llm_call_id": llm_call_id,
                "provider_attempt_id": attempt_id,
                "model": "test-model",
                "messages": [],
            },
        },
        {
            "sequence": sequence_start + 1,
            "kind": "llm.provider.response",
            "context": dict(context),
            "data": {
                "task": task,
                "llm_call_id": llm_call_id,
                "provider_attempt_id": attempt_id,
                "status": "success",
            },
        },
        {
            "sequence": sequence_start + 2,
            "kind": "llm.output.accepted",
            "context": {**context, "llm_task": task},
            "data": {
                "task": task,
                "result": {} if result is None else dict(result),
            },
        },
    ]


def _pretherapy_fixture(
    *,
    include_intake_patch: bool = True,
    include_intake_response: bool = True,
    include_assessment: bool = True,
    intake_session_id: str | None = None,
    client_message_id: str | None = None,
    extra_intake_sessions: Sequence[str] = (),
) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    session_id = intake_session_id or str(uuid4())
    client_id = client_message_id or str(uuid4())
    request_id = str(uuid4())
    journey: list[dict[str, Any]] = [
        {
            "sequence": 1,
            "kind": "chat.submitted",
            "context": {
                "session_id": session_id,
                "client_message_id": client_id,
                "request_id": request_id,
            },
            "data": {"content": "I have trouble sleeping", "phase": "intake"},
        },
        {
            "sequence": 2,
            "kind": "chat.completed",
            "context": {
                "session_id": session_id,
                "client_message_id": client_id,
                "request_id": request_id,
            },
            "data": {"assistant_text": "Tell me more."},
        },
    ]
    for index, other_session in enumerate(extra_intake_sessions, start=1):
        other_client = str(uuid4())
        other_request = str(uuid4())
        journey.extend(
            [
                {
                    "sequence": 2 + index * 2 - 1,
                    "kind": "chat.submitted",
                    "context": {
                        "session_id": other_session,
                        "client_message_id": other_client,
                        "request_id": other_request,
                    },
                    "data": {"content": f"extra {index}", "phase": "intake"},
                },
                {
                    "sequence": 2 + index * 2,
                    "kind": "chat.completed",
                    "context": {
                        "session_id": other_session,
                        "client_message_id": other_client,
                        "request_id": other_request,
                    },
                    "data": {"assistant_text": "ok"},
                },
            ]
        )

    trace: list[dict[str, Any]] = [
        {"sequence": 1, "kind": "llm.call.started", "context": {}, "data": {}},
    ]
    seq = 2
    if include_intake_patch:
        events = _structured_call_events(
            task="intake_patch",
            session_id=session_id,
            client_message_id=client_id,
            llm_call_id="llm-patch",
            attempt_id="attempt-patch",
            sequence_start=seq,
            result={"notes": "extracted"},
        )
        trace.extend(events)
        seq += 3
    if include_intake_response:
        trace.append(
            {
                "sequence": seq,
                "kind": "llm.provider.request",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_id,
                },
                "data": {
                    "task": "intake_response",
                    "messages": [],
                    "model": "test-model",
                },
            }
        )
        seq += 1
    if include_assessment:
        events = _structured_call_events(
            task="assessment",
            session_id=session_id,
            client_message_id=None,
            llm_call_id="llm-assess",
            attempt_id="attempt-assess",
            sequence_start=seq,
            result={"styles": []},
        )
        trace.extend(events)
    return session_id, client_id, journey, trace


def test_pretherapy_provider_evidence_complete_passes(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-pretherapy-ok")
    _session_id, _client_id, journey, trace = _pretherapy_fixture()
    _write_journey(run_dir, journey)
    _write_trace(run_dir, trace)
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=0,
        initial_ready_reached=True,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert codes.isdisjoint(_PRETHERAPY_CODES)


@pytest.mark.parametrize(
    ("omit", "expected"),
    [
        ("intake_patch", "intake_patch_chain"),
        ("intake_response", "missing_intake_response"),
        ("assessment", "assessment_chain"),
    ],
)
def test_pretherapy_provider_evidence_missing_matrix(
    tmp_path: Path,
    omit: str,
    expected: str,
) -> None:
    run_dir = allocate_run_directory(tmp_path / f"run-pretherapy-omit-{omit}")
    _session_id, _client_id, journey, trace = _pretherapy_fixture(
        include_intake_patch=omit != "intake_patch",
        include_intake_response=omit != "intake_response",
        include_assessment=omit != "assessment",
    )
    _write_journey(run_dir, journey)
    _write_trace(run_dir, trace)
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=0,
        initial_ready_reached=True,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert expected in codes


def test_pretherapy_assessment_requires_exactly_one_intake_session(
    tmp_path: Path,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-pretherapy-multi-intake")
    _session_id, _client_id, journey, trace = _pretherapy_fixture(
        extra_intake_sessions=[str(uuid4())],
    )
    _write_journey(run_dir, journey)
    _write_trace(run_dir, trace)
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=0,
        initial_ready_reached=True,
        therapy_sessions=[],
    )
    findings = [f for f in audit.findings if f.code == "assessment_chain"]
    assert findings
    assert any("exactly one intake session" in finding.message for finding in findings)


def test_pretherapy_assessment_zero_intake_sessions_fails(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-pretherapy-zero-intake")
    _write_trace(
        run_dir,
        [
            {"sequence": 1, "kind": "llm.call.started", "context": {}, "data": {}},
            {
                "sequence": 2,
                "kind": "llm.provider.request",
                "context": {},
                "data": {"task": "therapy_response", "messages": []},
            },
        ],
    )
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=True,
        configured_sessions=0,
        initial_ready_reached=True,
        therapy_sessions=[],
    )
    findings = [f for f in audit.findings if f.code == "assessment_chain"]
    assert findings
    assert any("exactly one intake session" in finding.message for finding in findings)


def _insert_message(
    path: Path,
    *,
    session_id: str,
    client_message_id: str,
    role: str,
    content: str,
    sequence: int,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO messages (
                id, session_id, sequence, role, content, client_message_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, '2020-01-01T00:00:01Z')
            """,
            (str(uuid4()), session_id, sequence, role, content, client_message_id),
        )
        conn.commit()
    finally:
        conn.close()


def _write_journey(run_dir: Path, events: list[dict[str, Any]]) -> None:
    write_private_text(
        run_dir / "journey.jsonl",
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
    )


def test_journey_chat_persistence_completed_and_message_failed(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-journey-persist")
    snapshot = run_dir / "runtime" / "db_snapshot.sqlite"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    session_id = str(uuid4())
    client_ok = str(uuid4())
    client_fail = str(uuid4())
    request_ok = str(uuid4())
    request_fail = str(uuid4())
    store = SQLiteStore(snapshot)
    store.initialize()
    conn = sqlite3.connect(snapshot)
    try:
        conn.execute(
            """
            INSERT INTO sessions (
                id, kind, plan_id, started_at, ended_at, review_json
            ) VALUES (?, 'intake', NULL, '2020-01-01T00:00:00Z', NULL, NULL)
            """,
            (session_id,),
        )
        conn.commit()
    finally:
        conn.close()
    _insert_message(
        snapshot,
        session_id=session_id,
        client_message_id=client_ok,
        role="user",
        content="patient says hi",
        sequence=1,
    )
    _insert_message(
        snapshot,
        session_id=session_id,
        client_message_id=client_ok,
        role="assistant",
        content="therapist replies",
        sequence=2,
    )
    _insert_message(
        snapshot,
        session_id=session_id,
        client_message_id=client_fail,
        role="user",
        content="failed turn",
        sequence=3,
    )
    _write_journey(
        run_dir,
        [
            {
                "sequence": 1,
                "kind": "chat.submitted",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_ok,
                    "request_id": request_ok,
                },
                "data": {"content": "patient says hi", "phase": "intake"},
            },
            {
                "sequence": 2,
                "kind": "chat.completed",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_ok,
                    "request_id": request_ok,
                },
                "data": {"assistant_text": "therapist replies"},
            },
            {
                "sequence": 3,
                "kind": "chat.submitted",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_fail,
                    "request_id": request_fail,
                },
                "data": {"content": "failed turn", "phase": "intake"},
            },
            {
                "sequence": 4,
                "kind": "chat.failed",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_fail,
                    "request_id": request_fail,
                },
                "data": {
                    "error_code": "chat_invalid_llm_output",
                    "error_message": "bad",
                    "api_error": {"event_type": "message_failed"},
                },
            },
        ],
    )
    _write_trace(run_dir, [])
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=False,
        configured_sessions=0,
        initial_ready_reached=False,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert "missing_user_message" not in codes
    assert "missing_assistant_message" not in codes
    assert "unexpected_assistant_message" not in codes
    assert "user_content_mismatch" not in codes
    assert "assistant_content_mismatch" not in codes
    assert "chat_journey_cardinality" not in codes


def test_journey_chat_persistence_cardinality_and_na(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-journey-card")
    snapshot = run_dir / "runtime" / "db_snapshot.sqlite"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(snapshot)
    store.initialize()
    session_id = str(uuid4())
    client_dup = str(uuid4())
    client_multi = str(uuid4())
    client_open = str(uuid4())
    request_dup = str(uuid4())
    request_multi = str(uuid4())
    request_open = str(uuid4())
    conn = sqlite3.connect(snapshot)
    try:
        conn.execute(
            """
            INSERT INTO sessions (
                id, kind, plan_id, started_at, ended_at, review_json
            ) VALUES (?, 'intake', NULL, '2020-01-01T00:00:00Z', NULL, NULL)
            """,
            (session_id,),
        )
        conn.commit()
    finally:
        conn.close()
    # Corrupt rows that must NOT produce persistence findings when cardinality fails.
    _insert_message(
        snapshot,
        session_id=session_id,
        client_message_id=client_dup,
        role="user",
        content="wrong",
        sequence=1,
    )
    _write_journey(
        run_dir,
        [
            {
                "sequence": 1,
                "kind": "chat.submitted",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_dup,
                    "request_id": request_dup,
                },
                "data": {"content": "one"},
            },
            {
                "sequence": 2,
                "kind": "chat.submitted",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_dup,
                    "request_id": request_dup,
                },
                "data": {"content": "two"},
            },
            {
                "sequence": 3,
                "kind": "chat.submitted",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_multi,
                    "request_id": request_multi,
                },
                "data": {"content": "once"},
            },
            {
                "sequence": 4,
                "kind": "chat.completed",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_multi,
                    "request_id": request_multi,
                },
                "data": {"assistant_text": "a"},
            },
            {
                "sequence": 5,
                "kind": "chat.failed",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_multi,
                    "request_id": request_multi,
                },
                "data": {"error_code": "x", "error_message": "y"},
            },
            {
                "sequence": 6,
                "kind": "chat.submitted",
                "context": {
                    "session_id": session_id,
                    "client_message_id": client_open,
                    "request_id": request_open,
                },
                "data": {"content": "open"},
            },
        ],
    )
    _write_trace(run_dir, [])
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=False,
        configured_sessions=0,
        initial_ready_reached=False,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    na_codes = {item.code for item in audit.not_applicable}
    assert "chat_journey_cardinality" in codes
    assert "missing_user_message" not in codes
    assert "user_content_mismatch" not in codes
    assert "chat_persistence" in na_codes


def test_journey_chat_persistence_malformed_identity(tmp_path: Path) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-journey-identity")
    snapshot = run_dir / "runtime" / "db_snapshot.sqlite"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(snapshot)
    store.initialize()
    _write_journey(
        run_dir,
        [
            {
                "sequence": 1,
                "kind": "chat.submitted",
                "context": {"session_id": str(uuid4())},
                "data": {"content": "missing ids"},
            },
        ],
    )
    _write_trace(run_dir, [])
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=False,
        configured_sessions=0,
        initial_ready_reached=False,
        therapy_sessions=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert "chat_journey_identity" in codes
    assert "missing_user_message" not in codes
    assert "user_content_mismatch" not in codes
    assert "assistant_content_mismatch" not in codes
    assert "chat_journey_cardinality" not in codes


def test_partial_session_missing_message_does_not_require_review(
    tmp_path: Path,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-partial-session")
    snapshot = run_dir / "runtime" / "db_snapshot.sqlite"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    session_id = str(uuid4())
    client_message_id = str(uuid4())
    plan_id = str(uuid4())
    store = SQLiteStore(snapshot)
    store.initialize()
    conn = sqlite3.connect(snapshot)
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
            ) VALUES (?, 'therapy', ?, '2020-01-01T00:00:00Z', NULL, NULL)
            """,
            (session_id, plan_id),
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
    # Only user row; assistant deliberately missing.
    _insert_message(
        snapshot,
        session_id=session_id,
        client_message_id=client_message_id,
        role="user",
        content="hello",
        sequence=1,
    )
    _write_trace(run_dir, [])
    audit = run_mechanical_audit(
        run_dir=run_dir,
        provider_trace_required=False,
        configured_sessions=1,
        initial_ready_reached=True,
        therapy_sessions=[
            {
                "session_id": session_id,
                "post_session_entered": False,
                "turns": [
                    {
                        "client_message_id": client_message_id,
                        "patient_text": "hello",
                        "assistant_text": "reply",
                    }
                ],
            }
        ],
    )
    codes = {finding.code for finding in audit.findings}
    na_codes = {item.code for item in audit.not_applicable}
    assert "missing_assistant_message" in codes
    assert "missing_review" not in codes
    assert "missing_session_checkpoint" not in codes
    assert "session_checkpoint" in na_codes
    assert "session_completion" in na_codes


def test_artifact_relative_paths_includes_pending_audit_and_run(
    tmp_path: Path,
) -> None:
    run_dir = allocate_run_directory(tmp_path / "run-artifacts")
    write_private_text(run_dir / "journey.jsonl", "{}\n")
    paths = artifact_relative_paths(run_dir)
    assert "audit.md" in paths
    assert "run.json" in paths
    assert "journey.jsonl" in paths
    assert "transcript.md" not in paths
