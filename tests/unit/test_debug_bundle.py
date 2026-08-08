"""Unit tests for debug bundle helpers and export."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import jung.debug_bundle as debug_bundle
from jung.debug_bundle import (
    _matching_git_root,
    build_manifest_llm_info,
    classify_unresolved_problems,
    export_db_snapshot,
    extract_touched_ids,
    finalize_debug_bundle,
    git_commit,
    write_manifest,
)
from jung.diagnostics import DiagnosticRun, diagnostic_context
from jung.domain.models import Profile
from jung.llm.gateway import LLMTask, ModelPolicy, StructuredOutputMode
from jung.persistence.sqlite_store import SQLiteStore


def test_write_manifest_and_export_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "jung.db"
    store = SQLiteStore(db_path)
    store.initialize()

    run_dir = tmp_path / "run"
    with DiagnosticRun(run_dir, secret_values=["sekrit"]) as recorder:
        policies = {
            LLMTask.INTAKE_PATCH: ModelPolicy(
                task=LLMTask.INTAKE_PATCH,
                model="m1",
                temperature=0.0,
                timeout_seconds=30.0,
                structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
            )
        }
        write_manifest(
            recorder,
            llm=build_manifest_llm_info(
                provider_url="http://user:sekrit@127.0.0.1:8080/v1?x=1",
                policies=policies,
            ),
        )
        recorder.record(
            "chat.turn.failed",
            {
                "error_code": "invalid_llm_output",
                "retryable": True,
                "source": "generation",
            },
        )
        recorder.mark_run_failed()
        finalize_debug_bundle(recorder, store)

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["diagnostic_schema_version"] == 4
    assert manifest["database_schema_version_expected"] == 5
    assert "sekrit" not in json.dumps(manifest)
    assert manifest["llm"]["provider_url"] == "http://127.0.0.1:8080/v1"
    assert manifest["llm"]["tasks"]["intake_patch"]["model"] == "m1"
    assert (run_dir / "state.json").exists()
    assert (run_dir / "transcript.md").exists()
    assert (run_dir / "failure_summary.md").exists()
    assert oct((run_dir / "manifest.json").stat().st_mode & 0o777) == "0o600"

    snapshot = export_db_snapshot(run_dir=run_dir, database=db_path)
    assert snapshot.exists()
    assert oct(snapshot.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(FileExistsError):
        export_db_snapshot(run_dir=run_dir, database=db_path)
    with pytest.raises(FileNotFoundError):
        export_db_snapshot(run_dir=tmp_path / "missing", database=db_path)


def test_export_db_snapshot_handles_reserved_path_chars(tmp_path: Path) -> None:
    db_dir = tmp_path / "db with spaces?#frag"
    db_dir.mkdir()
    db_path = db_dir / "jung.db"
    store = SQLiteStore(db_path)
    store.initialize()
    store.update_profile(
        Profile(name="Alex", primary_language="English"),
        intake_session_id=uuid4(),
        now=datetime.now(UTC),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    snapshot = export_db_snapshot(run_dir=run_dir, database=db_path)
    assert snapshot.exists()
    conn = sqlite3.connect(snapshot)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert len(tables) > 0


def test_export_db_snapshot_cleans_up_after_post_create_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "jung.db"
    SQLiteStore(db_path).initialize()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    destination = run_dir / "db_snapshot.sqlite"

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("forced connect failure")

    monkeypatch.setattr(debug_bundle.sqlite3, "connect", boom)
    with pytest.raises(sqlite3.OperationalError, match="forced connect failure"):
        export_db_snapshot(run_dir=run_dir, database=db_path)
    assert not destination.exists()


def test_export_db_snapshot_cleans_up_when_close_fails_after_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "jung.db"
    SQLiteStore(db_path).initialize()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    destination = run_dir / "db_snapshot.sqlite"

    real_close = debug_bundle.os.close

    def close_then_fail(fd: int) -> None:
        real_close(fd)
        raise OSError("forced close failure")

    monkeypatch.setattr(debug_bundle.os, "close", close_then_fail)
    with pytest.raises(OSError, match="forced close failure"):
        export_db_snapshot(run_dir=run_dir, database=db_path)
    assert not destination.exists()


def test_finalize_records_runtime_error_when_plan_query_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "jung.db"
    store = SQLiteStore(db_path)
    store.initialize()
    session_id = uuid4()
    store.update_profile(
        Profile(name="Alex", primary_language="English"),
        intake_session_id=session_id,
        now=datetime.now(UTC),
    )

    def fail_plans(session_id):
        raise RuntimeError("plan query failed")

    monkeypatch.setattr(store, "list_plans_for_session", fail_plans)

    run_dir = tmp_path / "run"
    with DiagnosticRun(run_dir) as recorder:
        with diagnostic_context(session_id=str(session_id)):
            recorder.record("chat.turn.started", {})
        finalize_debug_bundle(recorder, store)

    assert not (run_dir / "state.json").exists()
    events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    finalize_errors = [
        e
        for e in events
        if e["kind"] == "runtime.error"
        and e["data"].get("phase") == "debug_bundle_finalize"
    ]
    assert len(finalize_errors) == 1
    assert finalize_errors[0]["data"]["error_type"] == "RuntimeError"


def test_git_commit_rejects_unrelated_git_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unrelated = tmp_path / "unrelated"
    (unrelated / ".git").mkdir(parents=True)
    fake_module = unrelated / "site-packages" / "jung" / "debug_bundle.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("# fake\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        raise AssertionError("git rev-parse must not run for unrelated roots")

    monkeypatch.setattr(debug_bundle.subprocess, "run", fake_run)
    assert _matching_git_root(fake_module.resolve()) is None
    monkeypatch.setattr(debug_bundle, "__file__", str(fake_module))
    assert git_commit() is None
    assert calls == []


def test_git_commit_uses_matching_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "checkout"
    module = root / "src" / "jung" / "debug_bundle.py"
    module.parent.mkdir(parents=True)
    module.write_text("# fake\n", encoding="utf-8")
    (root / ".git").mkdir()

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        result = MagicMock()
        result.returncode = 0
        result.stdout = "abc123\n"
        return result

    monkeypatch.setattr(debug_bundle.subprocess, "run", fake_run)
    monkeypatch.setattr(debug_bundle, "__file__", str(module))
    assert git_commit() == "abc123"
    assert calls == [["git", "-C", str(root.resolve()), "rev-parse", "HEAD"]]


def test_extract_touched_ids_ignores_raw_body_uuids() -> None:
    events = [
        {
            "kind": "llm.provider.request",
            "context": {"session_id": "11111111-1111-1111-1111-111111111111"},
            "data": {
                "messages": [
                    {
                        "role": "user",
                        "content": "mention 22222222-2222-2222-2222-222222222222",
                    }
                ]
            },
        }
    ]
    touched = extract_touched_ids(events)
    assert touched["session_id"] == {"11111111-1111-1111-1111-111111111111"}
    assert "22222222-2222-2222-2222-222222222222" not in touched["session_id"]


def test_correction_events_alone_do_not_force_failure_summary(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    store = SQLiteStore(tmp_path / "db.sqlite")
    store.initialize()
    with DiagnosticRun(run_dir) as recorder:
        recorder.record(
            "llm.validation.failed",
            {
                "output_type": "X",
                "attempt": "initial",
                "trigger": "semantic_validation",
                "reason": "bad",
            },
        )
        recorder.record(
            "llm.correction.started",
            {"output_type": "X", "correction_trigger": "semantic_validation"},
        )
        recorder.record("llm.output.accepted", {"output_type": "X", "result": {}})
        recorder.record("llm.call.completed", {})
        finalize_debug_bundle(recorder, store)
    assert not (run_dir / "failure_summary.md").exists()


def test_write_failed_classified(tmp_path: Path) -> None:
    with DiagnosticRun(tmp_path / "run") as recorder:
        recorder._write_failed = True
        problems = classify_unresolved_problems(
            recorder=recorder,
            events=[],
            state={"operations": [], "sessions": [], "messages_by_session": {}},
            primary_exception=None,
            cleanup_exception=None,
        )
    assert any("write_failed" in problem for problem in problems)


def test_open_session_trailing_user_classified_as_unresolved(tmp_path: Path) -> None:
    session_id = str(uuid4())
    client_message_id = str(uuid4())
    with DiagnosticRun(tmp_path / "run") as recorder:
        problems = classify_unresolved_problems(
            recorder=recorder,
            events=[],
            state={
                "sessions": [
                    {
                        "id": session_id,
                        "ended_at": None,
                    }
                ],
                "messages_by_session": {
                    session_id: [
                        {
                            "role": "user",
                            "client_message_id": client_message_id,
                            "content": "hello",
                        }
                    ]
                },
                "operations": [],
            },
            primary_exception=None,
            cleanup_exception=None,
        )
    assert any(
        "unanswered user message on open session" in problem
        and session_id in problem
        and client_message_id in problem
        for problem in problems
    )
