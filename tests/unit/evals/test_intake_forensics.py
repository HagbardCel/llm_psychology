"""Deterministic unit tests for intake-turn forensic commit decision matrix."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from evals.simulation.intake_forensics import UNKNOWN, build_intake_turn_reports
from jung.persistence.sqlite_store import SQLiteStore


def _trace_event(
    kind: str,
    *,
    client_message_id: str,
    request_id: str | None,
    sequence: int,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {"client_message_id": client_message_id}
    if request_id is not None:
        context["request_id"] = request_id
    return {
        "sequence": sequence,
        "kind": kind,
        "context": context,
        "data": {} if data is None else data,
    }


def _write_intake_snapshot(
    path: Path,
    *,
    turns: list[tuple[str, str, bool]],
) -> str:
    """Create minimal intake DB.

    ``turns`` entries are ``(client_message_id, patient_text, has_assistant)``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(path)
    store.initialize()
    session_id = str(uuid4())
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO sessions (
                id, kind, plan_id, started_at, ended_at, review_json
            ) VALUES (?, 'intake', NULL, '2020-01-01T00:00:00Z', NULL, NULL)
            """,
            (session_id,),
        )
        sequence = 0
        for client_message_id, patient_text, has_assistant in turns:
            sequence += 1
            conn.execute(
                """
                INSERT INTO messages (
                    id, session_id, sequence, role, content, client_message_id,
                    created_at
                ) VALUES (?, ?, ?, 'user', ?, ?, '2020-01-01T00:00:01Z')
                """,
                (str(uuid4()), session_id, sequence, patient_text, client_message_id),
            )
            if has_assistant:
                sequence += 1
                conn.execute(
                    """
                    INSERT INTO messages (
                        id, session_id, sequence, role, content, client_message_id,
                        created_at
                    ) VALUES (?, ?, ?, 'assistant', ?, ?, '2020-01-01T00:00:02Z')
                    """,
                    (
                        str(uuid4()),
                        session_id,
                        sequence,
                        "Tell me more.",
                        client_message_id,
                    ),
                )
        conn.commit()
    finally:
        conn.close()
    return session_id


def test_assistant_no_lifecycle_is_committed_ambiguous(tmp_path: Path) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_id = str(uuid4())
    _write_intake_snapshot(
        snapshot,
        turns=[(client_id, "I cannot sleep", True)],
    )
    reports = build_intake_turn_reports(trace=[], snapshot_path=snapshot)
    assert len(reports) == 1
    report = reports[0]
    assert report.durable_commit == "yes"
    assert report.commit_status == "committed_ambiguous"
    assert len(report.attempts) == 1
    assert report.attempts[0].persisted_attempt == "unknown"
    assert report.attempts[0].lifecycle_status == "lifecycle_missing"


def test_assistant_one_failed_attempt_is_committed_ambiguous(tmp_path: Path) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_id = str(uuid4())
    request_id = str(uuid4())
    _write_intake_snapshot(
        snapshot,
        turns=[(client_id, "I cannot sleep", True)],
    )
    trace = [
        _trace_event(
            "chat.turn.started",
            client_message_id=client_id,
            request_id=request_id,
            sequence=1,
        ),
        _trace_event(
            "chat.turn.failed",
            client_message_id=client_id,
            request_id=request_id,
            sequence=2,
            data={"error_code": "chat_invalid_llm_output"},
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    assert len(reports) == 1
    report = reports[0]
    assert report.durable_commit == "yes"
    assert report.commit_status == "committed_ambiguous"
    assert len(report.attempts) == 1
    attempt = report.attempts[0]
    assert attempt.request_id == request_id
    assert attempt.attempt_outcome == "failed"
    assert attempt.persisted_attempt == "unknown"
    assert attempt.failure_code == "chat_invalid_llm_output"


def test_two_evaluated_request_ids_discover_two_attempts(tmp_path: Path) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_id = str(uuid4())
    request_a = str(uuid4())
    request_b = str(uuid4())
    _write_intake_snapshot(
        snapshot,
        turns=[(client_id, "I cannot sleep", True)],
    )
    trace = [
        _trace_event(
            "intake.turn.evaluated",
            client_message_id=client_id,
            request_id=request_a,
            sequence=1,
            data={"merge_status": "empty_patch", "record_changed": False},
        ),
        _trace_event(
            "intake.turn.evaluated",
            client_message_id=client_id,
            request_id=request_b,
            sequence=2,
            data={"merge_status": "empty_patch", "record_changed": False},
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    assert len(reports) == 1
    report = reports[0]
    assert len(report.attempts) == 2
    assert {attempt.request_id for attempt in report.attempts} == {
        request_a,
        request_b,
    }
    assert all(
        attempt.lifecycle_status == "lifecycle_missing" for attempt in report.attempts
    )


def test_one_clean_identity_missing_completion_is_fallback(tmp_path: Path) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_id = str(uuid4())
    request_id = str(uuid4())
    _write_intake_snapshot(
        snapshot,
        turns=[(client_id, "I cannot sleep", True)],
    )
    trace = [
        _trace_event(
            "chat.turn.started",
            client_message_id=client_id,
            request_id=request_id,
            sequence=1,
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    assert len(reports) == 1
    report = reports[0]
    assert report.durable_commit == "yes"
    assert report.commit_status == "committed_fallback"
    assert len(report.attempts) == 1
    attempt = report.attempts[0]
    assert attempt.persisted_attempt == "yes"
    assert attempt.attempt_outcome == "unknown"
    assert "missing_chat_completion_diagnostic" in attempt.flags


def test_multi_attempt_ambiguous_marks_later_turn_unknown(tmp_path: Path) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_ambiguous = str(uuid4())
    client_later = str(uuid4())
    request_a = str(uuid4())
    request_b = str(uuid4())
    request_later = str(uuid4())
    _write_intake_snapshot(
        snapshot,
        turns=[
            (client_ambiguous, "first message", True),
            (client_later, "second message", True),
        ],
    )
    trace = [
        _trace_event(
            "chat.turn.started",
            client_message_id=client_ambiguous,
            request_id=request_a,
            sequence=1,
        ),
        _trace_event(
            "chat.turn.started",
            client_message_id=client_ambiguous,
            request_id=request_b,
            sequence=2,
        ),
        _trace_event(
            "chat.turn.started",
            client_message_id=client_later,
            request_id=request_later,
            sequence=3,
        ),
        _trace_event(
            "chat.turn.completed",
            client_message_id=client_later,
            request_id=request_later,
            sequence=4,
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    assert len(reports) == 2
    first, second = reports
    assert first.commit_status == "committed_ambiguous"
    assert all(attempt.persisted_attempt == "unknown" for attempt in first.attempts)
    assert second.durable_commit == "yes"
    assert second.commit_status == "committed_exact"
    assert len(second.attempts) == 1
    later = second.attempts[0]
    assert later.planned_record_changed is UNKNOWN
    assert later.persisted_record_changed is UNKNOWN
    assert later.pre_turn_next_item is UNKNOWN
    assert later.planned_next_item is UNKNOWN
    assert later.persisted_next_item is UNKNOWN
    assert later.planned_completeness_complete is UNKNOWN
    assert later.planned_max_turn_completion_blocked is UNKNOWN


def test_uncommitted_persisted_next_item_equals_pre_turn(tmp_path: Path) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_id = str(uuid4())
    request_id = str(uuid4())
    _write_intake_snapshot(
        snapshot,
        turns=[(client_id, "I cannot sleep", False)],
    )
    trace = [
        _trace_event(
            "chat.turn.started",
            client_message_id=client_id,
            request_id=request_id,
            sequence=1,
        ),
        _trace_event(
            "intake.turn.evaluated",
            client_message_id=client_id,
            request_id=request_id,
            sequence=2,
            data={
                "merge_status": "empty_patch",
                "record_changed": False,
                "next_required_item": "presenting_problem",
            },
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    assert len(reports) == 1
    report = reports[0]
    assert report.durable_commit == "no"
    assert report.commit_status == "uncommitted"
    attempt = report.attempts[0]
    assert attempt.persisted_attempt == "no"
    assert attempt.planned_next_item == "presenting_problem"
    assert attempt.persisted_next_item == attempt.pre_turn_next_item
    assert attempt.persisted_next_item != attempt.planned_next_item


def test_exact_multi_attempt_one_persisted_yes_others_no(tmp_path: Path) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_id = str(uuid4())
    request_ok = str(uuid4())
    request_other = str(uuid4())
    _write_intake_snapshot(
        snapshot,
        turns=[(client_id, "I cannot sleep", True)],
    )
    trace = [
        _trace_event(
            "chat.turn.started",
            client_message_id=client_id,
            request_id=request_other,
            sequence=1,
        ),
        _trace_event(
            "chat.turn.failed",
            client_message_id=client_id,
            request_id=request_other,
            sequence=2,
            data={"error_code": "chat_invalid_llm_output"},
        ),
        _trace_event(
            "chat.turn.started",
            client_message_id=client_id,
            request_id=request_ok,
            sequence=3,
        ),
        _trace_event(
            "chat.turn.completed",
            client_message_id=client_id,
            request_id=request_ok,
            sequence=4,
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    assert len(reports) == 1
    report = reports[0]
    assert report.commit_status == "committed_exact"
    by_request = {attempt.request_id: attempt for attempt in report.attempts}
    assert by_request[request_ok].persisted_attempt == "yes"
    assert by_request[request_other].persisted_attempt == "no"


def test_multiple_matching_completions_correlation_and_ambiguous(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_id = str(uuid4())
    request_a = str(uuid4())
    request_b = str(uuid4())
    _write_intake_snapshot(
        snapshot,
        turns=[(client_id, "I cannot sleep", True)],
    )
    trace = [
        _trace_event(
            "chat.turn.started",
            client_message_id=client_id,
            request_id=request_a,
            sequence=1,
        ),
        _trace_event(
            "chat.turn.completed",
            client_message_id=client_id,
            request_id=request_a,
            sequence=2,
        ),
        _trace_event(
            "chat.turn.started",
            client_message_id=client_id,
            request_id=request_b,
            sequence=3,
        ),
        _trace_event(
            "chat.turn.completed",
            client_message_id=client_id,
            request_id=request_b,
            sequence=4,
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    assert len(reports) == 1
    report = reports[0]
    assert report.commit_status == "committed_ambiguous"
    assert "duplicate_completion_terminals" in report.correlation_findings
    assert all(attempt.persisted_attempt == "unknown" for attempt in report.attempts)
