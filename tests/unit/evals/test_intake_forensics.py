"""Deterministic unit tests for intake-turn forensic commit decision matrix."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from evals.simulation.audit import _format_intake_attempt_detail
from evals.simulation.intake_forensics import (
    UNKNOWN,
    build_intake_turn_reports,
    format_count_evidence,
    format_path_evidence,
)
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.intake.extraction import (
    ExtractedIntakeEvidence,
    IntakeEvidenceField,
    IntakeExtraction,
)


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
    # First ambiguous turn keeps planned facts visible.
    assert report.attempts[0].planned_record_changed is False
    assert report.attempts[0].persisted_record_changed is UNKNOWN


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
    assert first.attempts[0].planned_record_changed is False
    assert first.attempts[0].persisted_record_changed is UNKNOWN
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


def test_missing_extraction_committed_changed_latches_second_turn(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_one = str(uuid4())
    client_two = str(uuid4())
    request_one = str(uuid4())
    request_two = str(uuid4())
    _write_intake_snapshot(
        snapshot,
        turns=[
            (client_one, "About six months", True),
            (client_two, "No self harm thoughts", True),
        ],
    )
    trace = [
        _trace_event(
            "chat.turn.started",
            client_message_id=client_one,
            request_id=request_one,
            sequence=1,
        ),
        _trace_event(
            "chat.turn.completed",
            client_message_id=client_one,
            request_id=request_one,
            sequence=2,
        ),
        _trace_event(
            "intake.turn.evaluated",
            client_message_id=client_one,
            request_id=request_one,
            sequence=3,
            data={
                "record_changed": True,
                "next_required_item": "duration",
                "merge_status": "applied",
            },
        ),
        _trace_event(
            "chat.turn.started",
            client_message_id=client_two,
            request_id=request_two,
            sequence=4,
        ),
        _trace_event(
            "chat.turn.completed",
            client_message_id=client_two,
            request_id=request_two,
            sequence=5,
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    assert len(reports) == 2
    turn_one, turn_two = reports
    assert turn_one.attempts[0].persisted_record_changed is True
    assert turn_one.attempts[0].persisted_next_item == "duration"
    assert turn_one.attempts[0].persisted_changed_paths is UNKNOWN
    assert (
        "missing_accepted_extraction_for_committed_change" in turn_one.attempts[0].flags
    )
    assert turn_two.attempts[0].pre_turn_next_item is UNKNOWN
    assert turn_two.attempts[0].planned_next_item is UNKNOWN


def test_missing_extraction_record_changed_false_retains_prior(
    tmp_path: Path,
) -> None:
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
            "chat.turn.completed",
            client_message_id=client_id,
            request_id=request_id,
            sequence=2,
        ),
        _trace_event(
            "intake.turn.evaluated",
            client_message_id=client_id,
            request_id=request_id,
            sequence=3,
            data={"record_changed": False, "merge_status": "empty_patch"},
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    attempt = reports[0].attempts[0]
    assert attempt.persisted_record_changed is False
    assert attempt.persisted_changed_paths == ()
    assert attempt.persisted_next_item == attempt.pre_turn_next_item


def test_missing_evaluated_record_changed_is_reconstruction_unavailable(
    tmp_path: Path,
) -> None:
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
            "chat.turn.completed",
            client_message_id=client_id,
            request_id=request_id,
            sequence=2,
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    attempt = reports[0].attempts[0]
    assert attempt.persisted_record_changed is UNKNOWN
    assert attempt.persisted_next_item is UNKNOWN
    assert "committed_state_reconstruction_unavailable" in attempt.flags


def test_unknown_scalar_and_path_rendering_not_iterated_as_characters() -> None:
    assert format_count_evidence(UNKNOWN) == UNKNOWN
    assert format_path_evidence(UNKNOWN) == UNKNOWN
    from evals.simulation.intake_forensics import IntakeAttemptReport

    attempt = IntakeAttemptReport(
        attempt_index=1,
        request_id="req",
        lifecycle_status="present",
        attempt_outcome="completed",
        persisted_attempt="unknown",
        failure_code=None,
        extraction_target=UNKNOWN,
        raw_count=UNKNOWN,
        retained_count=UNKNOWN,
        merge_status=UNKNOWN,
        planned_record_changed=UNKNOWN,
        persisted_record_changed=UNKNOWN,
        pre_turn_next_item=UNKNOWN,
        planned_next_item=UNKNOWN,
        persisted_next_item=UNKNOWN,
        planned_completeness_complete=UNKNOWN,
        planned_max_turn_completion_blocked=UNKNOWN,
        extraction_rows=(),
        validation_retained_paths=UNKNOWN,
        persisted_changed_paths=UNKNOWN,
        materialization_dropped_paths=UNKNOWN,
        merge_dropped_paths=UNKNOWN,
        drop_reasons=(),
        flags=(),
    )
    lines = _format_intake_attempt_detail(attempt)
    joined = "\n".join(lines)
    assert UNKNOWN in joined
    assert UNKNOWN not in joined.replace(UNKNOWN, "")


def test_missing_evaluated_counts_are_unknown_not_zero(tmp_path: Path) -> None:
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
            "chat.turn.completed",
            client_message_id=client_id,
            request_id=request_id,
            sequence=2,
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    attempt = reports[0].attempts[0]
    assert attempt.raw_count is UNKNOWN
    assert attempt.retained_count is UNKNOWN


def _llm_accepted_event(
    *,
    client_message_id: str,
    request_id: str,
    sequence: int,
    extraction: IntakeExtraction,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "kind": "llm.output.accepted",
        "context": {
            "client_message_id": client_message_id,
            "request_id": request_id,
            "llm_task": "intake_patch",
            "llm_call_id": "llm-1",
        },
        "data": {
            "output_type": "IntakeExtraction",
            "result": extraction.model_dump(mode="json"),
        },
    }


def test_committed_first_attempt_survives_later_failed_attempt(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_c1 = str(uuid4())
    client_c2 = str(uuid4())
    request_r1 = str(uuid4())
    request_r2 = str(uuid4())
    patient_turn_one = (
        "I am not thinking about harming myself or anyone else. "
        "I have no urgent medical needs. "
        "I have been anxious in seminars lately."
    )
    _write_intake_snapshot(
        snapshot,
        turns=[
            (client_c1, patient_turn_one, True),
            (client_c2, "Second patient turn.", False),
        ],
    )
    extraction = IntakeExtraction(
        evidence=[
            ExtractedIntakeEvidence(
                field=IntakeEvidenceField.SAFETY_SELF_HARM,
                response_status="informative",
                value="denied",
                evidence_quote="not thinking about harming myself",
            ),
            ExtractedIntakeEvidence(
                field=IntakeEvidenceField.SAFETY_HARM_TO_OTHERS,
                response_status="informative",
                value="denied",
                evidence_quote="not thinking about harming myself or anyone else",
            ),
            ExtractedIntakeEvidence(
                field=IntakeEvidenceField.SAFETY_MEDICAL_URGENCY,
                response_status="informative",
                value="none",
                evidence_quote="no urgent medical needs",
            ),
            ExtractedIntakeEvidence(
                field=IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                response_status="informative",
                value="anxiety in seminars",
                evidence_quote="anxious in seminars lately",
            ),
        ]
    )
    trace = [
        _trace_event(
            "chat.turn.started",
            client_message_id=client_c1,
            request_id=request_r1,
            sequence=1,
        ),
        _llm_accepted_event(
            client_message_id=client_c1,
            request_id=request_r1,
            sequence=2,
            extraction=extraction,
        ),
        _trace_event(
            "intake.turn.evaluated",
            client_message_id=client_c1,
            request_id=request_r1,
            sequence=3,
            data={
                "merge_status": "applied",
                "record_changed": True,
            },
        ),
        _trace_event(
            "chat.turn.completed",
            client_message_id=client_c1,
            request_id=request_r1,
            sequence=4,
        ),
        _trace_event(
            "chat.turn.started",
            client_message_id=client_c1,
            request_id=request_r2,
            sequence=5,
        ),
        _trace_event(
            "chat.turn.failed",
            client_message_id=client_c1,
            request_id=request_r2,
            sequence=6,
            data={"error_code": "chat_invalid_llm_output"},
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    assert len(reports) == 2
    turn_one, turn_two = reports
    assert turn_one.commit_status == "committed_exact"
    by_request = {attempt.request_id: attempt for attempt in turn_one.attempts}
    committed = by_request[request_r1]
    failed = by_request[request_r2]
    assert committed.persisted_attempt == "yes"
    assert failed.persisted_attempt == "no"
    assert committed.persisted_next_item == "duration"
    assert turn_two.attempts[0].pre_turn_next_item == "duration"


def test_null_evaluated_counts_do_not_override_replay_counts(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "db_snapshot.sqlite"
    client_id = str(uuid4())
    request_id = str(uuid4())
    patient_text = "I have been anxious in seminars lately."
    _write_intake_snapshot(
        snapshot,
        turns=[(client_id, patient_text, True)],
    )
    extraction = IntakeExtraction(
        evidence=[
            ExtractedIntakeEvidence(
                field=IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                response_status="informative",
                value="anxiety in seminars",
                evidence_quote="anxious in seminars lately",
            )
        ]
    )
    trace = [
        _trace_event(
            "chat.turn.started",
            client_message_id=client_id,
            request_id=request_id,
            sequence=1,
        ),
        _llm_accepted_event(
            client_message_id=client_id,
            request_id=request_id,
            sequence=2,
            extraction=extraction,
        ),
        _trace_event(
            "intake.turn.evaluated",
            client_message_id=client_id,
            request_id=request_id,
            sequence=3,
            data={
                "merge_status": "applied",
                "record_changed": True,
                "raw_evidence_count": None,
                "retained_evidence_count": None,
            },
        ),
        _trace_event(
            "chat.turn.completed",
            client_message_id=client_id,
            request_id=request_id,
            sequence=4,
        ),
    ]
    reports = build_intake_turn_reports(trace=trace, snapshot_path=snapshot)
    attempt = reports[0].attempts[0]
    assert attempt.raw_count == 1
    assert attempt.retained_count == 1
