"""Unit tests for debug bundle helpers and export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jung.debug_bundle import (
    build_manifest_llm_info,
    classify_unresolved_problems,
    export_db_snapshot,
    extract_touched_ids,
    finalize_debug_bundle,
    write_manifest,
)
from jung.diagnostics import DiagnosticRun
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
    assert manifest["diagnostic_schema_version"] == 2
    assert manifest["database_schema_version_expected"] == 3
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
            state={"chat_turns": [], "operations": []},
            primary_exception=None,
            cleanup_exception=None,
        )
    assert any("write_failed" in problem for problem in problems)
