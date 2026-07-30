"""Integration coverage for diagnostic capture across a chat turn."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from jung.composition import application_context
from jung.config import ApplicationSettings
from jung.diagnostics import DiagnosticCaptureError, DiagnosticRun, diagnostic_context
from jung.domain.commands import SendMessage, UpdateProfile
from jung.domain.models import ChatTurnStatus, Profile, Stage
from jung.llm.fake import FakeLLM
from jung.llm.gateway import LLMSettings
from jung.persistence.sqlite_store import SCHEMA_VERSION, SQLiteStore

from .application_fixtures import (
    build_test_application,
    intake_message_expectations,
    wait_for_chat_turn,
)

pytestmark = pytest.mark.asyncio


def _load_trace(run_dir: Path) -> list[dict[str, object]]:
    lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _kinds(events: list[dict[str, object]]) -> list[str]:
    return [str(event["kind"]) for event in events]


async def test_diagnostic_chat_turn_causal_chain(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"

    with DiagnosticRun(run_dir, metadata={"test": "causal-chain"}) as recorder:
        store = SQLiteStore(db_path, recorder=recorder)
        store.initialize()
        store.backup_to(recorder.artifact_path("database-start.sqlite"))

        fake = FakeLLM(
            intake_message_expectations("Welcome. Tell me what brings you here.")
        )
        async with build_test_application(store, fake, recorder=recorder) as runtime:
            with diagnostic_context(request_id=str(uuid4())):
                await runtime.application.update_profile(
                    UpdateProfile(
                        expected_revision=0,
                        profile=Profile(name="Alex", primary_language="English"),
                    )
                )
                session = (await runtime.application.get_snapshot()).active_session
                assert session is not None
                turn = await runtime.application.submit_message(
                    SendMessage(
                        expected_revision=(
                            await runtime.application.get_snapshot()
                        ).revision,
                        session_id=session.id,
                        client_message_id=uuid4(),
                        content="I feel anxious.",
                        request_id=uuid4(),
                    )
                )
                completed = await wait_for_chat_turn(
                    runtime.application,
                    turn.id,
                    ChatTurnStatus.COMPLETE,
                )
                assert completed.status is ChatTurnStatus.COMPLETE

        store.backup_to(recorder.artifact_path("database-end.sqlite"))

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_status"] == "success"
    assert manifest["evidence_complete"] is True
    assert manifest["run_status_scope"] == "runtime_lifecycle"

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert "store.call.start" in kinds
    assert "store.call.complete" in kinds
    assert "database.sql" in kinds
    assert "application.event" in kinds
    assert "task.scheduled" in kinds
    assert "task.started" in kinds
    assert "task.completed" in kinds
    assert "llm.call.start" in kinds
    assert "llm.call.complete" in kinds

    turn_id = str(turn.id)
    chat_events = [
        event
        for event in events
        if event.get("context", {}).get("turn_id") == turn_id  # type: ignore[union-attr]
        or (
            isinstance(event.get("data"), dict)
            and str(event["data"]).find(turn_id) >= 0
        )
    ]
    assert chat_events

    start_db = run_dir / "database-start.sqlite"
    end_db = run_dir / "database-end.sqlite"
    assert start_db.is_file()
    assert end_db.is_file()
    for path in (start_db, end_db):
        conn = sqlite3.connect(path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert int(version) >= 1
        finally:
            conn.close()

    end_conn = sqlite3.connect(end_db)
    try:
        messages = end_conn.execute(
            "SELECT role, content FROM messages ORDER BY sequence"
        ).fetchall()
    finally:
        end_conn.close()
    assert any(role == "user" and "anxious" in content for role, content in messages)
    assert any(role == "assistant" and content.strip() for role, content in messages)


async def test_backup_to_rejects_existing_and_sets_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "source.db"
    store = SQLiteStore(db_path)
    store.initialize()
    dest = tmp_path / "backup.sqlite"
    store.backup_to(dest)
    assert dest.is_file()
    assert oct(dest.stat().st_mode & 0o777) == "0o600"
    assert list(tmp_path.glob(".backup.sqlite.*.tmp")) == []
    with sqlite3.connect(dest) as conn:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION
    with pytest.raises(FileExistsError):
        store.backup_to(dest)


async def test_backup_to_cleans_temp_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "source.db"
    store = SQLiteStore(db_path)
    store.initialize()
    dest = tmp_path / "backup-fail.sqlite"

    def boom(src: object, dst: object) -> None:
        raise OSError("publish failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="publish failed"):
        store.backup_to(dest)
    assert not dest.exists()
    assert list(tmp_path.glob(".backup-fail.sqlite.*.tmp")) == []


def _assert_snapshot_terminal(
    events: list[dict[str, object]], *, phase: str, artifact: str
) -> None:
    starts = [
        event
        for event in events
        if event["kind"] == "database.snapshot.start"
        and event["data"]["phase"] == phase
        and event["data"]["artifact"] == artifact
    ]
    terminals = [
        event
        for event in events
        if event["kind"] in {"database.snapshot.complete", "database.snapshot.error"}
        and event["data"]["phase"] == phase
        and event["data"]["artifact"] == artifact
    ]
    assert len(starts) == 1
    assert len(terminals) == 1


async def test_application_context_diagnostic_lifecycle_happy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", ClosingFakeLLM)
    run_dir = tmp_path / "composed-run"
    settings = ApplicationSettings(
        database_path=tmp_path / "composed.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        debug_run_dir=run_dir,
        shutdown_timeout_seconds=2.0,
    )
    async with application_context(settings) as runtime:
        assert runtime.recorder is not None
        snapshot = await runtime.application.get_snapshot()
        assert snapshot.stage is Stage.SETUP

    assert (run_dir / "database-start.sqlite").is_file()
    assert (run_dir / "database-end.sqlite").is_file()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_status"] == "success"
    assert manifest["evidence_complete"] is True
    events = _load_trace(run_dir)
    _assert_snapshot_terminal(events, phase="start", artifact="database-start.sqlite")
    _assert_snapshot_terminal(events, phase="end", artifact="database-end.sqlite")


async def test_application_context_start_snapshot_failure_still_attempts_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", ClosingFakeLLM)
    run_dir = tmp_path / "start-fail-run"
    settings = ApplicationSettings(
        database_path=tmp_path / "start-fail.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        debug_run_dir=run_dir,
        shutdown_timeout_seconds=2.0,
    )

    original = SQLiteStore.backup_to
    calls = {"n": 0}
    injected = RuntimeError("start snapshot boom")

    def flaky_backup(self: SQLiteStore, destination: Path) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise injected
        return original(self, destination)

    monkeypatch.setattr(SQLiteStore, "backup_to", flaky_backup)
    with pytest.raises(RuntimeError) as exc_info:
        async with application_context(settings):
            pass
    assert exc_info.value is injected
    assert calls["n"] >= 2
    assert not (run_dir / "database-start.sqlite").exists()
    assert (run_dir / "database-end.sqlite").is_file()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_status"] == "failed"
    assert manifest["evidence_complete"] is False
    events = _load_trace(run_dir)
    start_kinds = [
        event["kind"]
        for event in events
        if event["data"].get("phase") == "start"
        and str(event["kind"]).startswith("database.snapshot.")
    ]
    assert start_kinds == ["database.snapshot.start", "database.snapshot.error"]
    _assert_snapshot_terminal(events, phase="end", artifact="database-end.sqlite")


async def test_application_context_records_cleanup_errors_first_and_later(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime exception wins as primary, but all cleanup failures are recorded."""

    body_exc = RuntimeError("body failed")
    shutdown_exc = RuntimeError("shutdown failed")
    llm_close_exc = RuntimeError("llm close failed")

    class CloseFailLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            raise llm_close_exc

    async def failing_shutdown(self: object, *, timeout_seconds: float) -> None:
        raise shutdown_exc

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", CloseFailLLM)
    monkeypatch.setattr("jung.composition.TaskSupervisor.shutdown", failing_shutdown)

    run_dir = tmp_path / "cleanup-events"
    settings = ApplicationSettings(
        database_path=tmp_path / "cleanup-events.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        debug_run_dir=run_dir,
        shutdown_timeout_seconds=2.0,
    )

    with pytest.raises(RuntimeError) as exc_info:
        async with application_context(settings):
            raise body_exc

    assert exc_info.value is body_exc

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_status"] == "failed"
    assert manifest["evidence_complete"] is True

    events = _load_trace(run_dir)
    cleanup_events = [
        event
        for event in events
        if str(event["kind"]) == "runtime.cleanup.error"
    ]
    assert any(
        ev["data"]["step"] == "supervisor.shutdown"
        and ev["data"]["selected_as_cleanup_error"] is True
        for ev in cleanup_events
    )
    assert any(
        ev["data"]["step"] == "llm.aclose"
        and ev["data"]["selected_as_cleanup_error"] is False
        for ev in cleanup_events
    )


async def test_application_context_end_snapshot_cancel_does_not_mask_shutdown_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-snapshot cancellation is secondary when cleanup already failed."""

    shutdown_exc = RuntimeError("shutdown failed")

    class ClosingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            return None

    async def failing_shutdown(self: object, *, timeout_seconds: float) -> None:
        raise shutdown_exc

    original_capture_snapshot = None
    import jung.composition as composition_module

    original_capture_snapshot = composition_module._capture_snapshot

    async def cancel_on_end_snapshot(
        *,
        store: SQLiteStore,
        recorder: object,
        settings: object,
        phase: str,
    ) -> None:
        if phase == "end":
            raise asyncio.CancelledError()
        await original_capture_snapshot(
            store=store,
            recorder=recorder,  # type: ignore[arg-type]
            settings=settings,  # type: ignore[arg-type]
            phase=phase,
        )

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", ClosingFakeLLM)
    monkeypatch.setattr("jung.composition.TaskSupervisor.shutdown", failing_shutdown)
    monkeypatch.setattr(
        "jung.composition._capture_snapshot", cancel_on_end_snapshot
    )

    run_dir = tmp_path / "shutdown-end-cancel"
    settings = ApplicationSettings(
        database_path=tmp_path / "shutdown-end-cancel.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        debug_run_dir=run_dir,
        shutdown_timeout_seconds=2.0,
    )

    with pytest.raises(RuntimeError) as exc_info:
        async with application_context(settings):
            pass

    assert exc_info.value is shutdown_exc

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_status"] == "failed"
    assert manifest["evidence_complete"] is True

    events = _load_trace(run_dir)
    cleanup_events = [
        event
        for event in events
        if str(event["kind"]) == "runtime.cleanup.error"
    ]
    assert any(
        ev["data"]["step"] == "supervisor.shutdown"
        and ev["data"]["selected_as_cleanup_error"] is True
        for ev in cleanup_events
    )
    assert any(
        ev["data"]["step"] == "database.end_snapshot"
        and ev["data"]["selected_as_cleanup_error"] is False
        for ev in cleanup_events
    )


@pytest.mark.parametrize("end_snapshot_raises", [False, True])
async def test_application_context_end_snapshot_cancel_drains_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    end_snapshot_raises: bool,
) -> None:
    """Cancellation during end snapshot must drain the to_thread worker."""

    class ClosingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", ClosingFakeLLM)

    end_started = threading.Event()
    end_release = threading.Event()
    end_finished = threading.Event()

    original_backup_to = SQLiteStore.backup_to

    def blocking_backup_to(self: SQLiteStore, destination: Path) -> None:
        if destination.name == "database-end.sqlite":
            end_started.set()
            try:
                end_release.wait(timeout=5.0)
                if end_snapshot_raises:
                    # Simulate failure after cancellation; _capture_snapshot must still drain.
                    raise RuntimeError("backup boom")
                original_backup_to(self, destination)
            finally:
                end_finished.set()
            return
        original_backup_to(self, destination)

    monkeypatch.setattr(SQLiteStore, "backup_to", blocking_backup_to)

    run_dir = tmp_path / (
        "end-snapshot-cancel-drains-fail" if end_snapshot_raises else "end-snapshot-cancel-drains-ok"
    )
    settings = ApplicationSettings(
        database_path=tmp_path / "end-snapshot-cancel-drains.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        debug_run_dir=run_dir,
        shutdown_timeout_seconds=2.0,
    )

    async def runner() -> None:
        async with application_context(settings):
            await asyncio.sleep(0.01)

    task = asyncio.create_task(runner())
    await asyncio.to_thread(end_started.wait, 2.0)
    assert end_started.is_set() is True

    # Cancel while end snapshot worker is blocked; application_context must not finalize yet.
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    assert not end_finished.is_set()

    end_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert end_finished.is_set() is True

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_status"] == "failed"
    assert manifest["evidence_complete"] is (not end_snapshot_raises)


async def test_application_context_end_snapshot_failure_is_evidence_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot creation failures are diagnostic evidence issues, not cleanup exceptions."""

    class ClosingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", ClosingFakeLLM)

    original_backup_to = SQLiteStore.backup_to

    def boom_on_end(self: SQLiteStore, destination: Path) -> None:
        if destination.name == "database-end.sqlite":
            raise RuntimeError("end snapshot boom")
        original_backup_to(self, destination)

    monkeypatch.setattr(SQLiteStore, "backup_to", boom_on_end)

    run_dir = tmp_path / "end-snapshot-evidence-incomplete"
    settings = ApplicationSettings(
        database_path=tmp_path / "end-snapshot-evidence-incomplete.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        debug_run_dir=run_dir,
        shutdown_timeout_seconds=2.0,
    )

    with pytest.raises(DiagnosticCaptureError, match="evidence incomplete"):
        async with application_context(settings):
            pass

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    # Evidence-incomplete without a primary error is reported via DiagnosticCaptureError,
    # but the diagnostic run_status reflects whether a primary exception was present.
    assert manifest["run_status"] == "success"
    assert manifest["evidence_complete"] is False

    events = _load_trace(run_dir)
    runtime_cleanup_events = [
        e
        for e in events
        if str(e["kind"]) == "runtime.cleanup.error"
    ]
    assert not any(
        e["data"]["step"] == "database.end_snapshot"
        for e in runtime_cleanup_events
    )
