"""Integration coverage for diagnostic capture across a chat turn."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from jung.diagnostics import DiagnosticRun, diagnostic_context
from jung.domain.commands import SendMessage, UpdateProfile
from jung.domain.models import ChatTurnStatus, Profile
from jung.llm.fake import FakeLLM
from jung.persistence.sqlite_store import SQLiteStore

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
    with pytest.raises(FileExistsError):
        store.backup_to(dest)
