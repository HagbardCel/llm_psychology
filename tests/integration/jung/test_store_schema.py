"""Schema initialization and connection lifecycle tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from jung.domain.errors import PersistenceFailure, RevisionConflict
from jung.domain.models import Profile, Stage
from jung.persistence import _sqlite_support as sql
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
    with store._connect() as conn:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
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


@pytest.mark.parametrize("version", [1, 99])
def test_incompatible_user_version_is_rejected(store_path: Path, version: int) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    with sqlite3.connect(store_path) as conn:
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    with pytest.raises(PersistenceFailure):
        store.initialize()


def test_close_and_reopen_preserves_state(store: SQLiteStore) -> None:
    profile = Profile(name="Alex", primary_language="English")
    now = datetime.now(UTC)
    store.update_profile(
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
        store.update_profile(
            Profile(name="Alex", primary_language="English"),
            expected_revision=99,
            intake_session_id=uuid4(),
            now=datetime.now(UTC),
        )
    assert store.get_app_state().revision == 0


@pytest.mark.parametrize("table_name", sorted(sql.TARGET_TABLES))
def test_version_zero_partial_target_schema_is_rejected(
    store_path: Path,
    table_name: str,
) -> None:
    with sqlite3.connect(store_path) as conn:
        conn.execute(f'CREATE TABLE "{table_name}" (placeholder INTEGER)')
        conn.commit()

    with pytest.raises(
        PersistenceFailure,
        match="unexpected tables without schema version",
    ):
        SQLiteStore(store_path).initialize()


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
    assert tables.isdisjoint(sql.TARGET_TABLES)


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


def test_chat_turn_user_message_id_unique(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    session_id = str(uuid4())
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_open_session(conn, session_id)
        now = datetime.now(UTC).isoformat()
        user_message_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO messages (id, session_id, sequence, role, content, created_at)
            VALUES (?, ?, 1, 'user', 'hello', ?)
            """,
            (user_message_id, session_id, now),
        )
        conn.execute(
            """
            INSERT INTO chat_turns (
                id, session_id, client_message_id, status, user_message_id,
                assistant_message_id, error_code, error_message, retryable,
                created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, 'failed', ?, NULL, 'test_failure', NULL, 0, ?, ?, ?)
            """,
            (str(uuid4()), session_id, str(uuid4()), user_message_id, now, now, now),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO chat_turns (
                    id, session_id, client_message_id, status, user_message_id,
                    assistant_message_id, error_code, error_message, retryable,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, 'failed', ?, NULL, 'test_failure', NULL, 0, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    session_id,
                    str(uuid4()),
                    user_message_id,
                    now,
                    now,
                    now,
                ),
            )
            conn.commit()


def test_chat_turn_assistant_message_id_unique(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    session_id = str(uuid4())
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_open_session(conn, session_id)
        now = datetime.now(UTC).isoformat()
        user_message_id_one = str(uuid4())
        user_message_id_two = str(uuid4())
        assistant_message_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO messages (id, session_id, sequence, role, content, created_at)
            VALUES (?, ?, 1, 'user', 'one', ?)
            """,
            (user_message_id_one, session_id, now),
        )
        conn.execute(
            """
            INSERT INTO messages (id, session_id, sequence, role, content, created_at)
            VALUES (?, ?, 2, 'user', 'two', ?)
            """,
            (user_message_id_two, session_id, now),
        )
        conn.execute(
            """
            INSERT INTO messages (id, session_id, sequence, role, content, created_at)
            VALUES (?, ?, 3, 'assistant', 'reply', ?)
            """,
            (assistant_message_id, session_id, now),
        )
        conn.execute(
            """
            INSERT INTO chat_turns (
                id, session_id, client_message_id, status, user_message_id,
                assistant_message_id, error_code, error_message, retryable,
                created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, 'complete', ?, ?, NULL, NULL, 0, ?, ?, ?)
            """,
            (
                str(uuid4()),
                session_id,
                str(uuid4()),
                user_message_id_one,
                assistant_message_id,
                now,
                now,
                now,
            ),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO chat_turns (
                    id, session_id, client_message_id, status, user_message_id,
                    assistant_message_id, error_code, error_message, retryable,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, 'complete', ?, ?, NULL, NULL, 0, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    session_id,
                    str(uuid4()),
                    user_message_id_two,
                    assistant_message_id,
                    now,
                    now,
                    now,
                ),
            )
            conn.commit()


def test_singleton_rejects_second_pending_turn(store_path: Path) -> None:
    store = SQLiteStore(store_path)
    store.initialize()
    session_id = str(uuid4())
    with sqlite3.connect(store_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_open_session(conn, session_id)
        message_id, turn_id, client_id, now = _pending_turn_params(conn, session_id)
        conn.execute(
            """
            INSERT INTO chat_turns (
                id, session_id, client_message_id, status, user_message_id,
                assistant_message_id, error_code, error_message, retryable,
                created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, 'pending', ?, NULL, NULL, NULL, 0, ?, ?, NULL)
            """,
            (turn_id, session_id, client_id, message_id, now, now),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO chat_turns (
                    id, session_id, client_message_id, status, user_message_id,
                    assistant_message_id, error_code, error_message, retryable,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, 'pending', ?, NULL, NULL, NULL, 0, ?, ?, NULL)
                """,
                _second_pending_turn_insert_params(conn),
            )
            conn.commit()


def _pending_turn_params(
    conn: sqlite3.Connection, session_id: str | None = None
) -> tuple[str, str, str, str]:
    if session_id is None:
        session_id = conn.execute("SELECT id FROM sessions LIMIT 1").fetchone()[0]
    now = datetime.now(UTC).isoformat()
    message_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO messages (id, session_id, sequence, role, content, created_at)
        VALUES (?, ?, 1, 'user', 'hello', ?)
        """,
        (message_id, session_id, now),
    )
    return message_id, str(uuid4()), str(uuid4()), now


def _second_pending_turn_insert_params(
    conn: sqlite3.Connection,
) -> tuple[str, str, str, str, str, str]:
    session_id = conn.execute("SELECT id FROM sessions LIMIT 1").fetchone()[0]
    now = datetime.now(UTC).isoformat()
    message_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO messages (id, session_id, sequence, role, content, created_at)
        VALUES (?, ?, 2, 'user', 'again', ?)
        """,
        (message_id, session_id, now),
    )
    return str(uuid4()), session_id, str(uuid4()), message_id, now, now


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
    ("table", "update_sql", "params"),
    [
        (
            "operations",
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
            "operations",
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
            "chat_turns",
            """
            UPDATE chat_turns
            SET status = 'complete', assistant_message_id = NULL
            WHERE id = ?
            """,
            lambda conn: (
                conn.execute("SELECT id FROM chat_turns LIMIT 1").fetchone()[0],
            ),
        ),
        (
            "chat_turns",
            """
            UPDATE chat_turns
            SET status = 'failed', error_code = NULL
            WHERE id = ?
            """,
            lambda conn: (
                conn.execute("SELECT id FROM chat_turns LIMIT 1").fetchone()[0],
            ),
        ),
        (
            "operations",
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
            "operations",
            """
            UPDATE operations
            SET status = 'pending', retryable = 1
            WHERE id = ?
            """,
            lambda conn: (
                conn.execute("SELECT id FROM operations LIMIT 1").fetchone()[0],
            ),
        ),
        (
            "chat_turns",
            """
            UPDATE chat_turns
            SET status = 'pending', error_message = 'stale'
            WHERE id = ?
            """,
            lambda conn: (
                conn.execute("SELECT id FROM chat_turns LIMIT 1").fetchone()[0],
            ),
        ),
        (
            "chat_turns",
            """
            UPDATE chat_turns
            SET status = 'complete', retryable = 1
            WHERE id = ?
            """,
            lambda conn: (
                conn.execute("SELECT id FROM chat_turns LIMIT 1").fetchone()[0],
            ),
        ),
    ],
)
def test_status_shape_checks_reject_invalid_rows(
    store_path: Path, table: str, update_sql: str, params
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
        message_id, turn_id, client_id, _ = _pending_turn_params(conn, session_id)
        conn.execute(
            """
            INSERT INTO chat_turns (
                id, session_id, client_message_id, status, user_message_id,
                assistant_message_id, error_code, error_message, retryable,
                created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, 'pending', ?, NULL, NULL, NULL, 0, ?, ?, NULL)
            """,
            (turn_id, session_id, client_id, message_id, now, now),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(update_sql, params(conn))
            conn.commit()
