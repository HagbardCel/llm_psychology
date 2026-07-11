"""Schema initialization and connection lifecycle tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from jung.domain.errors import PersistenceFailure, RevisionConflict
from jung.domain.models import Profile, Stage
from jung.persistence.sqlite_store import SCHEMA_VERSION, SQLiteStore


def test_initialize_creates_fresh_setup_state(store: SQLiteStore) -> None:
    state = store.get_app_state()
    assert state.stage == Stage.SETUP
    assert state.revision == 0


def test_initialize_is_idempotent(store: SQLiteStore) -> None:
    store.initialize()
    assert store.get_app_state().revision == 0


def test_foreign_keys_and_wal_enabled(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    with store._connect() as conn:
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert fk == 1
    assert journal.lower() == "wal"
    assert busy == 5000


def test_user_version_is_set(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    with sqlite3.connect(store_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION


def test_incompatible_user_version_is_rejected(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
    with pytest.raises(PersistenceFailure):
        store.initialize()


def test_close_and_reopen_preserves_state(store: SQLiteStore) -> None:
    profile = Profile(name="Alex", primary_language="English")
    now = datetime.now(UTC)
    store.complete_profile_and_open_intake(
        profile,
        expected_revision=0,
        intake_session_id=uuid4(),
        now=now,
    )
    reopened = SQLiteStore(store.database_path)
    reopened.initialize()
    assert reopened.get_app_state().stage == Stage.INTAKE
    assert reopened.get_active_session() is not None


def test_stale_revision_rejected(store: SQLiteStore) -> None:
    with pytest.raises(RevisionConflict):
        store.replace_profile(
            Profile(name="Alex", primary_language="English"),
            expected_revision=99,
            now=datetime.now(UTC),
        )
    assert store.get_app_state().revision == 0
