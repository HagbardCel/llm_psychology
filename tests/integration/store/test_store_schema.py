"""Schema initialization and connection lifecycle tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from jung.domain.errors import InvariantViolation, PersistenceFailure
from jung.domain.models import Profile, Stage
from jung.persistence import _sqlite_support as sql
from jung.persistence.sqlite_store import SCHEMA_VERSION, SQLiteStore

EXPECTED_TABLES = frozenset({"profile", "sessions", "plans", "messages", "operations"})


def test_initialize_creates_fresh_setup_state(store: SQLiteStore) -> None:
    facts = store.load_snapshot_facts()
    assert facts.stage == Stage.SETUP
    assert facts.profile_complete is False


def test_initialize_is_idempotent(store: SQLiteStore) -> None:
    store.initialize()
    assert store.load_snapshot_facts().stage == Stage.SETUP


def test_foreign_keys_and_wal_enabled(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    with store._connect() as conn:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert fk == 1
    assert journal.lower() == "wal"
    assert busy == 5000


def test_fresh_schema_has_current_version_and_tables(
    store_path: Path,
) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    with sqlite3.connect(store_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if not row[0].startswith("sqlite_")
        }
        message_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        message_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'messages'"
        ).fetchone()[0]
    assert version == SCHEMA_VERSION
    assert tables == EXPECTED_TABLES
    assert "client_message_id" in message_columns
    assert "role IN ('user', 'assistant')" in message_sql
    assert "UNIQUE (session_id, client_message_id, role)" in message_sql


@pytest.mark.parametrize(
    "version",
    [SCHEMA_VERSION - 1, SCHEMA_VERSION + 1],
)
def test_incompatible_user_version_is_rejected(
    store_path: Path,
    version: int,
) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    with sqlite3.connect(store_path) as conn:
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    with pytest.raises(
        PersistenceFailure,
        match=f"unsupported schema version {version}; reset the database",
    ):
        store.initialize()


def test_close_and_reopen_preserves_state(store: SQLiteStore) -> None:
    profile = Profile(name="Alex", primary_language="English")
    now = datetime.now(UTC)
    store.update_profile(
        profile,
        intake_session_id=uuid4(),
        now=now,
    )
    reopened = SQLiteStore(store.database_path)
    reopened.initialize()
    assert reopened.load_snapshot_facts().stage == Stage.INTAKE
    assert reopened.get_active_session() is not None


def test_version_zero_nonempty_database_is_rejected(store_path: Path) -> None:
    with sqlite3.connect(store_path) as conn:
        conn.execute("CREATE TABLE unexpected_table (placeholder INTEGER)")
        conn.commit()

    with pytest.raises(
        PersistenceFailure,
        match="unexpected tables without schema version",
    ):
        SQLiteStore(store_path).initialize()


def test_missing_profile_raises_invariant_violation(store: SQLiteStore) -> None:
    with sqlite3.connect(store.database_path) as conn:
        conn.execute("DELETE FROM profile WHERE singleton_id = 1")
        conn.commit()
    with pytest.raises(InvariantViolation, match="profile singleton is missing"):
        store.load_snapshot_facts()


def test_initialize_rolls_back_on_seed_failure(
    store_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SQLiteStore(store_path)
    original_seed = sql.seed_initial_state

    def failing_seed(conn: sqlite3.Connection) -> None:
        original_seed(conn)
        raise sqlite3.IntegrityError("forced initialization failure")

    monkeypatch.setattr(sql, "seed_initial_state", failing_seed)

    with pytest.raises(PersistenceFailure):
        store.initialize()

    with sqlite3.connect(store_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert version == 0
    assert tables.isdisjoint(EXPECTED_TABLES)


def _seed_open_session(
    conn: sqlite3.Connection, session_id: str, *, plan_id: str | None = None
) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO sessions (id, kind, plan_id, started_at, ended_at, summary, briefing_json)
        VALUES (?, 'intake', ?, ?, NULL, NULL, NULL)
        """,
        (session_id, plan_id, now),
    )


def test_singleton_rejects_second_open_session(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    session_id = str(uuid4())
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_open_session(conn, session_id)
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO sessions (id, kind, plan_id, started_at, ended_at, summary, briefing_json)
                VALUES (?, 'intake', NULL, ?, NULL, NULL, NULL)
                """,
                (str(uuid4()), datetime.now(UTC).isoformat()),
            )
            conn.commit()


def test_singleton_rejects_second_current_operation(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    session_id = str(uuid4())
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_open_session(conn, session_id)
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """
            INSERT INTO operations (
                id, kind, status, source_session_id, attempt, result_json,
                error_code, error_message, retryable, created_at, updated_at
            ) VALUES (?, 'assessment', 'pending', ?, 0, NULL, NULL, NULL, 0, ?, ?)
            """,
            (str(uuid4()), session_id, now, now),
        )
        conn.commit()

        # Use a distinct operation key so only the global current-operation
        # singleton index can reject this insert.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO operations (
                    id, kind, status, source_session_id, attempt, result_json,
                    error_code, error_message, retryable, created_at, updated_at
                ) VALUES (?, 'post_session', 'pending', ?, 0, NULL, NULL, NULL, 0, ?, ?)
                """,
                (str(uuid4()), session_id, now, now),
            )
            conn.commit()


def test_messages_role_check_rejects_invalid_role(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    session_id = str(uuid4())
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_open_session(conn, session_id)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO messages (
                    id, session_id, sequence, role, content, client_message_id, created_at
                ) VALUES (?, ?, 1, 'system', 'nope', ?, ?)
                """,
                (
                    str(uuid4()),
                    session_id,
                    str(uuid4()),
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()


def test_messages_require_client_message_id(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    session_id = str(uuid4())
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_open_session(conn, session_id)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO messages (
                    id, session_id, sequence, role, content, client_message_id, created_at
                ) VALUES (?, ?, 1, 'user', 'hello', NULL, ?)
                """,
                (str(uuid4()), session_id, datetime.now(UTC).isoformat()),
            )
            conn.commit()


def test_messages_unique_client_message_id_per_role(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    session_id = str(uuid4())
    client_message_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_open_session(conn, session_id)
        conn.execute(
            """
            INSERT INTO messages (
                id, session_id, sequence, role, content, client_message_id, created_at
            ) VALUES (?, ?, 1, 'user', 'hello', ?, ?)
            """,
            (str(uuid4()), session_id, client_message_id, now),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO messages (
                    id, session_id, sequence, role, content, client_message_id, created_at
                ) VALUES (?, ?, 2, 'user', 'dup', ?, ?)
                """,
                (str(uuid4()), session_id, client_message_id, now),
            )
            conn.commit()


def test_plan_empty_focus_rejected_by_schema(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    session_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_open_session(conn, session_id)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO plans (
                    id, version, selected_style, focus, themes_json, goals_json,
                    current_progress, planned_interventions_json,
                    revision_recommendations_json, session_briefing_json,
                    source_session_id, supersedes_plan_id, created_at
                ) VALUES (?, 1, 'cbt', ' ', '[]', '[]', 'ok', '[]', '[]', NULL, ?, NULL, ?)
                """,
                (str(uuid4()), session_id, now),
            )
            conn.commit()


def test_therapy_session_rejects_invalid_plan_id(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO sessions (id, kind, plan_id, started_at, ended_at, summary, briefing_json)
                VALUES (?, 'therapy', ?, ?, NULL, NULL, NULL)
                """,
                (str(uuid4()), str(uuid4()), datetime.now(UTC).isoformat()),
            )
            conn.commit()


@pytest.mark.parametrize(
    ("update_sql", "params"),
    [
        (
            """
            UPDATE operations
            SET status = 'complete', result_json = NULL
            WHERE id = ?
            """,
            lambda conn: (
                conn.execute("SELECT id FROM operations LIMIT 1").fetchone()[0],
            ),
        ),
        (
            """
            UPDATE operations
            SET status = 'failed', error_code = NULL
            WHERE id = ?
            """,
            lambda conn: (
                conn.execute("SELECT id FROM operations LIMIT 1").fetchone()[0],
            ),
        ),
        (
            """
            UPDATE operations
            SET status = 'pending', error_message = 'stale'
            WHERE id = ?
            """,
            lambda conn: (
                conn.execute("SELECT id FROM operations LIMIT 1").fetchone()[0],
            ),
        ),
        (
            """
            UPDATE operations
            SET status = 'pending', retryable = 1
            WHERE id = ?
            """,
            lambda conn: (
                conn.execute("SELECT id FROM operations LIMIT 1").fetchone()[0],
            ),
        ),
    ],
)
def test_operation_status_shape_checks_reject_invalid_rows(
    store_path: Path, update_sql: str, params
) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    session_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_open_session(conn, session_id)
        conn.execute(
            """
            INSERT INTO operations (
                id, kind, status, source_session_id, attempt, result_json,
                error_code, error_message, retryable, created_at, updated_at
            ) VALUES (?, 'assessment', 'pending', ?, 0, NULL, NULL, NULL, 0, ?, ?)
            """,
            (str(uuid4()), session_id, now, now),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(update_sql, params(conn))
            conn.commit()
