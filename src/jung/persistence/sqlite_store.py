"""Concrete SQLite persistence for the target single-user core."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from jung.domain.errors import (
    Busy,
    InvariantViolation,
    NotFound,
    PersistenceFailure,
    RevisionConflict,
)
from jung.domain.models import (
    AppState,
    ChatTurn,
    ChatTurnStatus,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    OperationStatus,
    Plan,
    Profile,
    Session,
    SessionKind,
    Stage,
    StoredProfile,
    WorkflowFacts,
    is_profile_complete,
)
from jung.persistence import _sqlite_support as sql

SCHEMA_VERSION = sql.SCHEMA_VERSION


class SQLiteStore:
    """Synchronous use-case store with one connection per operation."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> None:
        """Create schema and seed singleton state when needed."""
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version == 0:
                if sql.has_target_tables(conn):
                    raise PersistenceFailure(
                        "database has unexpected tables without schema version"
                    )
                sql.create_schema(conn)
                sql.assert_foreign_keys(conn)
                sql.seed_initial_state(conn)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                conn.commit()
                return
            if version != SCHEMA_VERSION:
                raise PersistenceFailure(
                    f"unsupported schema version {version}; reset the database"
                )

    def reset_database(self) -> None:
        """Remove the database files and recreate a fresh schema."""
        resolved = self._database_path.resolve()
        for dangerous in sql.DANGEROUS_DB_PATHS:
            if resolved == dangerous.resolve():
                raise PersistenceFailure(
                    f"refusing to reset production database at {resolved}"
                )
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{self._database_path}{suffix}")
            if path.exists():
                path.unlink()
        self.initialize()

    def get_app_state(self) -> AppState:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT stage, revision, created_at, updated_at FROM app_state WHERE singleton_id = 1"
            ).fetchone()
            if row is None:
                raise NotFound("app_state")
            return sql.row_to_app_state(row)

    def get_profile(self) -> StoredProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT name, primary_language, date_of_birth, notes,
                       derived_profile_json, current_plan_id, created_at, updated_at
                FROM profile WHERE singleton_id = 1
                """
            ).fetchone()
            if row is None:
                return None
            return sql.row_to_stored_profile(row)

    def get_current_plan(self) -> Plan | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT p.id, p.version, p.selected_style, p.focus, p.themes_json,
                       p.goals_json, p.current_progress, p.planned_interventions_json,
                       p.revision_recommendations_json, p.session_briefing_json,
                       p.source_session_id, p.supersedes_plan_id, p.created_at
                FROM profile pr
                JOIN plans p ON p.id = pr.current_plan_id
                WHERE pr.singleton_id = 1
                """
            ).fetchone()
            if row is None:
                return None
            return sql.row_to_plan(row)

    def list_sessions(self) -> list[Session]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, kind, plan_id, started_at, ended_at, summary, briefing_json
                FROM sessions
                ORDER BY started_at DESC
                """
            ).fetchall()
            return [sql.row_to_session(row) for row in rows]

    def get_session(self, session_id: UUID) -> Session | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, kind, plan_id, started_at, ended_at, summary, briefing_json
                FROM sessions WHERE id = ?
                """,
                (str(session_id),),
            ).fetchone()
            return sql.row_to_session(row) if row else None

    def list_messages(self, session_id: UUID) -> list[Message]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.id, m.session_id, m.sequence, m.role, m.content, m.created_at,
                       ct.client_message_id
                FROM messages m
                LEFT JOIN chat_turns ct ON ct.user_message_id = m.id
                WHERE m.session_id = ?
                ORDER BY m.sequence ASC
                """,
                (str(session_id),),
            ).fetchall()
            return [sql.row_to_message(row) for row in rows]

    def get_current_operation(self) -> Operation | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, kind, status, source_session_id, attempt, result_json,
                       error_code, error_message, retryable, created_at, updated_at,
                       started_at, completed_at
                FROM operations
                WHERE status IN ('pending', 'running', 'failed')
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            return sql.row_to_operation(row) if row else None

    def get_operation(self, operation_id: UUID) -> Operation | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, kind, status, source_session_id, attempt, result_json,
                       error_code, error_message, retryable, created_at, updated_at,
                       started_at, completed_at
                FROM operations WHERE id = ?
                """,
                (str(operation_id),),
            ).fetchone()
            return sql.row_to_operation(row) if row else None

    def get_chat_turn(self, turn_id: UUID) -> ChatTurn | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, client_message_id, status, user_message_id,
                       assistant_message_id, error_code, error_message, retryable,
                       created_at, updated_at, completed_at
                FROM chat_turns WHERE id = ?
                """,
                (str(turn_id),),
            ).fetchone()
            return sql.row_to_chat_turn(row) if row else None

    def get_chat_turn_by_client_id(
        self, session_id: UUID, client_message_id: UUID
    ) -> ChatTurn | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, client_message_id, status, user_message_id,
                       assistant_message_id, error_code, error_message, retryable,
                       created_at, updated_at, completed_at
                FROM chat_turns
                WHERE session_id = ? AND client_message_id = ?
                """,
                (str(session_id), str(client_message_id)),
            ).fetchone()
            return sql.row_to_chat_turn(row) if row else None

    def get_active_session(self) -> Session | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, kind, plan_id, started_at, ended_at, summary, briefing_json
                FROM sessions WHERE ended_at IS NULL
                LIMIT 1
                """
            ).fetchone()
            return sql.row_to_session(row) if row else None

    def get_active_chat_turn(self) -> ChatTurn | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, client_message_id, status, user_message_id,
                       assistant_message_id, error_code, error_message, retryable,
                       created_at, updated_at, completed_at
                FROM chat_turns
                WHERE status = 'pending'
                LIMIT 1
                """
            ).fetchone()
            return sql.row_to_chat_turn(row) if row else None

    def load_snapshot_facts(self) -> WorkflowFacts:
        with self._connect() as conn:
            return self._load_snapshot_facts(conn)

    def replace_profile(
        self,
        profile: Profile,
        *,
        expected_revision: int,
        now: datetime,
    ) -> AppState:
        def mutate(conn: sqlite3.Connection) -> None:
            stage = self._require_stage(conn, {Stage.SETUP, Stage.INTAKE})
            if stage == Stage.INTAKE and not is_profile_complete(profile):
                raise InvariantViolation(
                    "profile must remain complete during intake"
                )
            self._upsert_profile(conn, profile, now=now)

        return self._write(expected_revision, mutate)

    def complete_profile_and_open_intake(
        self,
        profile: Profile,
        *,
        expected_revision: int,
        intake_session_id: UUID,
        now: datetime,
    ) -> tuple[AppState, Session]:
        if not is_profile_complete(profile):
            raise InvariantViolation("profile must be complete")

        session_holder: dict[str, Session] = {}

        def mutate(conn: sqlite3.Connection) -> None:
            self._require_stage(conn, {Stage.SETUP})
            if conn.execute(
                "SELECT 1 FROM sessions WHERE ended_at IS NULL LIMIT 1"
            ).fetchone():
                raise InvariantViolation("open session already exists")
            self._upsert_profile(conn, profile, now=now)
            conn.execute(
                """
                INSERT INTO sessions (id, kind, plan_id, started_at, ended_at, summary, briefing_json)
                VALUES (?, ?, NULL, ?, NULL, NULL, NULL)
                """,
                (str(intake_session_id), SessionKind.INTAKE.value, sql.dt(now)),
            )
            self._set_stage(conn, Stage.INTAKE, now)
            row = conn.execute(
                """
                SELECT id, kind, plan_id, started_at, ended_at, summary, briefing_json
                FROM sessions WHERE id = ?
                """,
                (str(intake_session_id),),
            ).fetchone()
            session_holder["session"] = sql.row_to_session(row)

        state = self._write(expected_revision, mutate)
        return state, session_holder["session"]

    def finish_intake_and_create_assessment(
        self,
        *,
        expected_revision: int,
        intake_session_id: UUID,
        operation_id: UUID,
        now: datetime,
    ) -> tuple[AppState, Operation]:
        operation_holder: dict[str, Operation] = {}

        def mutate(conn: sqlite3.Connection) -> None:
            self._require_stage(conn, {Stage.INTAKE})
            session = self._require_open_session(conn, intake_session_id)
            if session.kind != SessionKind.INTAKE:
                raise InvariantViolation("session must be intake")
            conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?",
                (sql.dt(now), str(intake_session_id)),
            )
            existing = conn.execute(
                """
                SELECT id FROM operations
                WHERE kind = ? AND source_session_id = ?
                """,
                (OperationKind.ASSESSMENT.value, str(intake_session_id)),
            ).fetchone()
            if existing:
                operation_holder["operation"] = self._load_operation(
                    conn, UUID(existing[0])
                )
            else:
                conn.execute(
                    """
                    INSERT INTO operations (
                        id, kind, status, source_session_id, attempt, result_json,
                        error_code, error_message, retryable, created_at, updated_at,
                        started_at, completed_at
                    ) VALUES (?, ?, ?, ?, 0, NULL, NULL, NULL, 0, ?, ?, NULL, NULL)
                    """,
                    (
                        str(operation_id),
                        OperationKind.ASSESSMENT.value,
                        OperationStatus.PENDING.value,
                        str(intake_session_id),
                        sql.dt(now),
                        sql.dt(now),
                    ),
                )
                operation_holder["operation"] = self._load_operation(
                    conn, operation_id
                )
            self._set_stage(conn, Stage.ASSESSMENT, now)

        state = self._write(expected_revision, mutate)
        return state, operation_holder["operation"]

    def mark_operation_running(
        self,
        operation_id: UUID,
        *,
        now: datetime,
    ) -> Operation:
        def mutate(conn: sqlite3.Connection) -> None:
            cursor = conn.execute(
                """
                UPDATE operations
                SET status = ?, attempt = attempt + 1, started_at = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    OperationStatus.RUNNING.value,
                    sql.dt(now),
                    sql.dt(now),
                    str(operation_id),
                    OperationStatus.PENDING.value,
                ),
            )
            self._ensure_operation_updated(conn, cursor, operation_id)

        self._write(None, mutate)
        operation = self.get_operation(operation_id)
        assert operation is not None
        return operation

    def complete_assessment(
        self,
        operation_id: UUID,
        *,
        result: dict[str, Any],
        now: datetime,
    ) -> AppState:
        def mutate(conn: sqlite3.Connection) -> None:
            self._require_stage(conn, {Stage.ASSESSMENT})
            cursor = conn.execute(
                """
                UPDATE operations
                SET status = ?, result_json = ?, completed_at = ?, updated_at = ?,
                    error_code = NULL, error_message = NULL, retryable = 0
                WHERE id = ? AND status = ? AND kind = ?
                """,
                (
                    OperationStatus.COMPLETE.value,
                    sql.json_dumps(result),
                    sql.dt(now),
                    sql.dt(now),
                    str(operation_id),
                    OperationStatus.RUNNING.value,
                    OperationKind.ASSESSMENT.value,
                ),
            )
            self._ensure_operation_updated(conn, cursor, operation_id)
            self._set_stage(conn, Stage.STYLE_SELECTION, now)

        return self._write(None, mutate)

    def fail_operation(
        self,
        operation_id: UUID,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
        now: datetime,
    ) -> Operation:
        def mutate(conn: sqlite3.Connection) -> None:
            cursor = conn.execute(
                """
                UPDATE operations
                SET status = ?, error_code = ?, error_message = ?, retryable = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    OperationStatus.FAILED.value,
                    error_code,
                    error_message,
                    int(retryable),
                    sql.dt(now),
                    sql.dt(now),
                    str(operation_id),
                    OperationStatus.RUNNING.value,
                ),
            )
            self._ensure_operation_updated(conn, cursor, operation_id)

        self._write(None, mutate)
        operation = self.get_operation(operation_id)
        assert operation is not None
        return operation

    def retry_operation(
        self,
        operation_id: UUID,
        *,
        expected_revision: int,
        now: datetime,
    ) -> Operation:
        def mutate(conn: sqlite3.Connection) -> None:
            cursor = conn.execute(
                """
                UPDATE operations
                SET status = ?, error_code = NULL, error_message = NULL,
                    retryable = 0, updated_at = ?, completed_at = NULL, started_at = NULL
                WHERE id = ? AND status = ? AND retryable = 1
                """,
                (
                    OperationStatus.PENDING.value,
                    sql.dt(now),
                    str(operation_id),
                    OperationStatus.FAILED.value,
                ),
            )
            self._ensure_operation_updated(conn, cursor, operation_id)

        self._write(expected_revision, mutate)
        operation = self.get_operation(operation_id)
        assert operation is not None
        return operation

    def select_style_and_create_initial_plan(
        self,
        *,
        expected_revision: int,
        style_id: str,
        plan_id: UUID,
        focus: str,
        themes: list[str],
        goals: list[str],
        current_progress: str,
        planned_interventions: list[str],
        revision_recommendations: list[str],
        intake_session_id: UUID,
        now: datetime,
    ) -> tuple[AppState, Plan]:
        plan_holder: dict[str, Plan] = {}

        def mutate(conn: sqlite3.Connection) -> None:
            self._require_stage(conn, {Stage.STYLE_SELECTION})
            assessment = conn.execute(
                """
                SELECT result_json FROM operations
                WHERE kind = ? AND status = ?
                ORDER BY completed_at DESC LIMIT 1
                """,
                (OperationKind.ASSESSMENT.value, OperationStatus.COMPLETE.value),
            ).fetchone()
            if assessment is None or not assessment[0]:
                raise InvariantViolation("completed assessment result is required")
            conn.execute(
                """
                INSERT INTO plans (
                    id, version, selected_style, focus, themes_json, goals_json,
                    current_progress, planned_interventions_json,
                    revision_recommendations_json, session_briefing_json,
                    source_session_id, supersedes_plan_id, created_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)
                """,
                (
                    str(plan_id),
                    style_id,
                    focus,
                    sql.json_dumps(themes),
                    sql.json_dumps(goals),
                    current_progress,
                    sql.json_dumps(planned_interventions),
                    sql.json_dumps(revision_recommendations),
                    str(intake_session_id),
                    sql.dt(now),
                ),
            )
            conn.execute(
                "UPDATE profile SET current_plan_id = ?, updated_at = ? WHERE singleton_id = 1",
                (str(plan_id), sql.dt(now)),
            )
            self._set_stage(conn, Stage.READY, now)
            plan_holder["plan"] = self._load_plan(conn, plan_id)

        state = self._write(expected_revision, mutate)
        return state, plan_holder["plan"]

    def start_therapy_session(
        self,
        *,
        expected_revision: int,
        session_id: UUID,
        now: datetime,
    ) -> tuple[AppState, Session]:
        session_holder: dict[str, Session] = {}

        def mutate(conn: sqlite3.Connection) -> None:
            self._require_stage(conn, {Stage.READY})
            if conn.execute(
                "SELECT 1 FROM sessions WHERE ended_at IS NULL LIMIT 1"
            ).fetchone():
                raise Busy("an open session already exists")
            plan_row = conn.execute(
                "SELECT current_plan_id FROM profile WHERE singleton_id = 1"
            ).fetchone()
            if plan_row is None or plan_row[0] is None:
                raise InvariantViolation("current plan is required")
            conn.execute(
                """
                INSERT INTO sessions (id, kind, plan_id, started_at, ended_at, summary, briefing_json)
                VALUES (?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (
                    str(session_id),
                    SessionKind.THERAPY.value,
                    plan_row[0],
                    sql.dt(now),
                ),
            )
            self._set_stage(conn, Stage.THERAPY, now)
            row = conn.execute(
                """
                SELECT id, kind, plan_id, started_at, ended_at, summary, briefing_json
                FROM sessions WHERE id = ?
                """,
                (str(session_id),),
            ).fetchone()
            session_holder["session"] = sql.row_to_session(row)

        state = self._write(expected_revision, mutate)
        return state, session_holder["session"]

    def end_therapy_session(
        self,
        *,
        expected_revision: int,
        session_id: UUID,
        operation_id: UUID,
        now: datetime,
    ) -> tuple[AppState, Operation]:
        operation_holder: dict[str, Operation] = {}

        def mutate(conn: sqlite3.Connection) -> None:
            self._require_stage(conn, {Stage.THERAPY})
            session = self._require_open_session(conn, session_id)
            if session.kind != SessionKind.THERAPY:
                raise InvariantViolation("session must be therapy")
            conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?",
                (sql.dt(now), str(session_id)),
            )
            existing = conn.execute(
                """
                SELECT id FROM operations
                WHERE kind = ? AND source_session_id = ?
                """,
                (OperationKind.POST_SESSION.value, str(session_id)),
            ).fetchone()
            if existing:
                operation_holder["operation"] = self._load_operation(
                    conn, UUID(existing[0])
                )
            else:
                conn.execute(
                    """
                    INSERT INTO operations (
                        id, kind, status, source_session_id, attempt, result_json,
                        error_code, error_message, retryable, created_at, updated_at,
                        started_at, completed_at
                    ) VALUES (?, ?, ?, ?, 0, NULL, NULL, NULL, 0, ?, ?, NULL, NULL)
                    """,
                    (
                        str(operation_id),
                        OperationKind.POST_SESSION.value,
                        OperationStatus.PENDING.value,
                        str(session_id),
                        sql.dt(now),
                        sql.dt(now),
                    ),
                )
                operation_holder["operation"] = self._load_operation(
                    conn, operation_id
                )
            self._set_stage(conn, Stage.POST_SESSION, now)

        state = self._write(expected_revision, mutate)
        return state, operation_holder["operation"]

    def complete_post_session(
        self,
        operation_id: UUID,
        *,
        summary: str,
        briefing: dict[str, Any],
        derived_profile: dict[str, Any],
        plan_id: UUID,
        focus: str,
        themes: list[str],
        goals: list[str],
        current_progress: str,
        planned_interventions: list[str],
        revision_recommendations: list[str],
        now: datetime,
    ) -> AppState:
        def mutate(conn: sqlite3.Connection) -> None:
            self._require_stage(conn, {Stage.POST_SESSION})
            op_row = conn.execute(
                """
                SELECT kind, status, source_session_id
                FROM operations WHERE id = ?
                """,
                (str(operation_id),),
            ).fetchone()
            if op_row is None:
                raise NotFound(f"operation {operation_id}")
            if op_row[0] != OperationKind.POST_SESSION.value:
                raise InvariantViolation("operation must be post_session")
            if op_row[1] != OperationStatus.RUNNING.value:
                raise InvariantViolation("operation must be running")
            source_session_id = op_row[2]
            current_plan = self._require_current_plan(conn)
            new_version = current_plan.version + 1
            conn.execute(
                """
                UPDATE sessions
                SET summary = ?, briefing_json = ?
                WHERE id = ?
                """,
                (summary, sql.json_dumps(briefing), source_session_id),
            )
            conn.execute(
                """
                INSERT INTO plans (
                    id, version, selected_style, focus, themes_json, goals_json,
                    current_progress, planned_interventions_json,
                    revision_recommendations_json, session_briefing_json,
                    source_session_id, supersedes_plan_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(plan_id),
                    new_version,
                    current_plan.selected_style,
                    focus,
                    sql.json_dumps(themes),
                    sql.json_dumps(goals),
                    current_progress,
                    sql.json_dumps(planned_interventions),
                    sql.json_dumps(revision_recommendations),
                    sql.json_dumps(briefing),
                    source_session_id,
                    str(current_plan.id),
                    sql.dt(now),
                ),
            )
            conn.execute(
                """
                UPDATE profile
                SET derived_profile_json = ?, current_plan_id = ?, updated_at = ?
                WHERE singleton_id = 1
                """,
                (sql.json_dumps(derived_profile), str(plan_id), sql.dt(now)),
            )
            result = {"plan_id": str(plan_id), "version": new_version}
            cursor = conn.execute(
                """
                UPDATE operations
                SET status = ?, result_json = ?, completed_at = ?, updated_at = ?,
                    error_code = NULL, error_message = NULL, retryable = 0
                WHERE id = ? AND status = ? AND kind = ?
                """,
                (
                    OperationStatus.COMPLETE.value,
                    sql.json_dumps(result),
                    sql.dt(now),
                    sql.dt(now),
                    str(operation_id),
                    OperationStatus.RUNNING.value,
                    OperationKind.POST_SESSION.value,
                ),
            )
            self._ensure_operation_updated(conn, cursor, operation_id)
            self._set_stage(conn, Stage.READY, now)

        return self._write(None, mutate)

    def accept_chat_message(
        self,
        *,
        expected_revision: int,
        session_id: UUID,
        client_message_id: UUID,
        turn_id: UUID,
        user_message_id: UUID,
        content: str,
        now: datetime,
    ) -> tuple[AppState | None, ChatTurn]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._load_chat_turn_by_client_id(
                    conn, session_id, client_message_id
                )
                if existing is not None:
                    conn.rollback()
                    return None, existing

                revision = self._load_revision(conn)
                if revision != expected_revision:
                    raise RevisionConflict(expected_revision, revision)

                stage = self._load_stage(conn)
                if stage not in {Stage.INTAKE, Stage.THERAPY}:
                    raise InvariantViolation(
                        "chat is only allowed in intake or therapy"
                    )
                if conn.execute(
                    "SELECT 1 FROM chat_turns WHERE status = 'pending' LIMIT 1"
                ).fetchone():
                    raise Busy("another chat turn is pending")
                session = self._require_open_session(conn, session_id)
                if stage == Stage.INTAKE and session.kind != SessionKind.INTAKE:
                    raise InvariantViolation("intake chat requires intake session")
                if stage == Stage.THERAPY and session.kind != SessionKind.THERAPY:
                    raise InvariantViolation("therapy chat requires therapy session")

                sequence = self._next_sequence(conn, session_id)
                conn.execute(
                    """
                    INSERT INTO messages (id, session_id, sequence, role, content, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(user_message_id),
                        str(session_id),
                        sequence,
                        MessageRole.USER.value,
                        content,
                        sql.dt(now),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO chat_turns (
                        id, session_id, client_message_id, status, user_message_id,
                        assistant_message_id, error_code, error_message, retryable,
                        created_at, updated_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, 0, ?, ?, NULL)
                    """,
                    (
                        str(turn_id),
                        str(session_id),
                        str(client_message_id),
                        ChatTurnStatus.PENDING.value,
                        str(user_message_id),
                        sql.dt(now),
                        sql.dt(now),
                    ),
                )
                self._increment_revision(conn)
                turn = self._load_chat_turn(conn, turn_id)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                raise sql.translate_sqlite_error(exc) from exc

        return self.get_app_state(), turn

    def complete_chat_turn(
        self,
        turn_id: UUID,
        *,
        assistant_message_id: UUID,
        content: str,
        now: datetime,
    ) -> ChatTurn:
        def mutate(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT session_id FROM chat_turns WHERE id = ?",
                (str(turn_id),),
            ).fetchone()
            if row is None:
                raise NotFound(f"chat turn {turn_id}")
            session_id = UUID(row[0])
            sequence = self._next_sequence(conn, session_id)
            conn.execute(
                """
                INSERT INTO messages (id, session_id, sequence, role, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(assistant_message_id),
                    str(session_id),
                    sequence,
                    MessageRole.ASSISTANT.value,
                    content,
                    sql.dt(now),
                ),
            )
            cursor = conn.execute(
                """
                UPDATE chat_turns
                SET status = ?, assistant_message_id = ?, updated_at = ?, completed_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    ChatTurnStatus.COMPLETE.value,
                    str(assistant_message_id),
                    sql.dt(now),
                    sql.dt(now),
                    str(turn_id),
                    ChatTurnStatus.PENDING.value,
                ),
            )
            self._ensure_chat_turn_updated(conn, cursor, turn_id)

        self._write(None, mutate)
        turn = self.get_chat_turn(turn_id)
        assert turn is not None
        return turn

    def fail_chat_turn(
        self,
        turn_id: UUID,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
        now: datetime,
    ) -> ChatTurn:
        def mutate(conn: sqlite3.Connection) -> None:
            cursor = conn.execute(
                """
                UPDATE chat_turns
                SET status = ?, error_code = ?, error_message = ?, retryable = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    ChatTurnStatus.FAILED.value,
                    error_code,
                    error_message,
                    int(retryable),
                    sql.dt(now),
                    sql.dt(now),
                    str(turn_id),
                    ChatTurnStatus.PENDING.value,
                ),
            )
            self._ensure_chat_turn_updated(conn, cursor, turn_id)

        self._write(None, mutate)
        turn = self.get_chat_turn(turn_id)
        assert turn is not None
        return turn

    def retry_chat_turn(
        self,
        turn_id: UUID,
        *,
        now: datetime,
    ) -> ChatTurn:
        def mutate(conn: sqlite3.Connection) -> None:
            if conn.execute(
                "SELECT 1 FROM chat_turns WHERE status = 'pending' LIMIT 1"
            ).fetchone():
                raise Busy("another chat turn is pending")
            cursor = conn.execute(
                """
                UPDATE chat_turns
                SET status = ?, error_code = NULL, error_message = NULL,
                    retryable = 0, updated_at = ?, completed_at = NULL,
                    assistant_message_id = NULL
                WHERE id = ? AND status = ? AND retryable = 1
                """,
                (
                    ChatTurnStatus.PENDING.value,
                    sql.dt(now),
                    str(turn_id),
                    ChatTurnStatus.FAILED.value,
                ),
            )
            self._ensure_chat_turn_updated(conn, cursor, turn_id)

        self._write(None, mutate)
        turn = self.get_chat_turn(turn_id)
        assert turn is not None
        return turn

    def recover_stale_operations(self, *, now: datetime) -> list[Operation]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(
                    """
                    SELECT id FROM operations WHERE status = ?
                    """,
                    (OperationStatus.RUNNING.value,),
                ).fetchall()
                if not rows:
                    conn.rollback()
                    return []
                conn.execute(
                    """
                    UPDATE operations
                    SET status = ?, started_at = NULL, updated_at = ?
                    WHERE status = ?
                    """,
                    (
                        OperationStatus.PENDING.value,
                        sql.dt(now),
                        OperationStatus.RUNNING.value,
                    ),
                )
                recovered = [
                    self._load_operation(conn, UUID(row[0])) for row in rows
                ]
                self._increment_revision(conn)
                conn.commit()
                return recovered
            except Exception as exc:
                conn.rollback()
                raise sql.translate_sqlite_error(exc) from exc

    def recover_stale_chat_turns(self, *, now: datetime) -> list[ChatTurn]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(
                    "SELECT id FROM chat_turns WHERE status = ?",
                    (ChatTurnStatus.PENDING.value,),
                ).fetchall()
                if not rows:
                    conn.rollback()
                    return []
                conn.execute(
                    """
                    UPDATE chat_turns
                    SET status = ?, error_code = ?, error_message = ?, retryable = 1,
                        updated_at = ?, completed_at = ?
                    WHERE status = ?
                    """,
                    (
                        ChatTurnStatus.FAILED.value,
                        "stale_pending",
                        "pending chat turn recovered at startup",
                        sql.dt(now),
                        sql.dt(now),
                        ChatTurnStatus.PENDING.value,
                    ),
                )
                recovered = [
                    self._load_chat_turn(conn, UUID(row[0])) for row in rows
                ]
                self._increment_revision(conn)
                conn.commit()
                return recovered
            except Exception as exc:
                conn.rollback()
                raise sql.translate_sqlite_error(exc) from exc

    def _write(
        self,
        expected_revision: int | None,
        mutate: Callable[[sqlite3.Connection], None],
    ) -> AppState:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                revision = self._load_revision(conn)
                if expected_revision is not None and revision != expected_revision:
                    raise RevisionConflict(expected_revision, revision)
                mutate(conn)
                self._increment_revision(conn)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                raise sql.translate_sqlite_error(exc) from exc
        return self.get_app_state()

    @contextmanager
    def _connect(self):
        with sql.connect(self._database_path) as conn:
            yield conn

    def _ensure_operation_updated(
        self,
        conn: sqlite3.Connection,
        cursor: sqlite3.Cursor,
        operation_id: UUID,
    ) -> None:
        if cursor.rowcount:
            return
        row = conn.execute(
            "SELECT status FROM operations WHERE id = ?",
            (str(operation_id),),
        ).fetchone()
        if row is None:
            raise NotFound(f"operation {operation_id}")
        raise InvariantViolation(
            f"operation {operation_id} is in invalid state {row[0]}"
        )

    def _ensure_chat_turn_updated(
        self,
        conn: sqlite3.Connection,
        cursor: sqlite3.Cursor,
        turn_id: UUID,
    ) -> None:
        if cursor.rowcount:
            return
        row = conn.execute(
            "SELECT status FROM chat_turns WHERE id = ?",
            (str(turn_id),),
        ).fetchone()
        if row is None:
            raise NotFound(f"chat turn {turn_id}")
        raise InvariantViolation(
            f"chat turn {turn_id} is in invalid state {row[0]}"
        )

    def _load_chat_turn_by_client_id(
        self,
        conn: sqlite3.Connection,
        session_id: UUID,
        client_message_id: UUID,
    ) -> ChatTurn | None:
        row = conn.execute(
            """
            SELECT id, session_id, client_message_id, status, user_message_id,
                   assistant_message_id, error_code, error_message, retryable,
                   created_at, updated_at, completed_at
            FROM chat_turns
            WHERE session_id = ? AND client_message_id = ?
            """,
            (str(session_id), str(client_message_id)),
        ).fetchone()
        return sql.row_to_chat_turn(row) if row else None

    def _require_current_plan(self, conn: sqlite3.Connection) -> Plan:
        row = conn.execute(
            """
            SELECT p.id, p.version, p.selected_style, p.focus, p.themes_json,
                   p.goals_json, p.current_progress, p.planned_interventions_json,
                   p.revision_recommendations_json, p.session_briefing_json,
                   p.source_session_id, p.supersedes_plan_id, p.created_at
            FROM profile pr
            JOIN plans p ON p.id = pr.current_plan_id
            WHERE pr.singleton_id = 1
            """
        ).fetchone()
        if row is None:
            raise InvariantViolation("current plan is required")
        return sql.row_to_plan(row)

    def _load_revision(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT revision FROM app_state WHERE singleton_id = 1"
        ).fetchone()
        if row is None:
            raise NotFound("app_state")
        return int(row[0])

    def _increment_revision(self, conn: sqlite3.Connection) -> None:
        now = sql.dt(datetime.now(UTC))
        conn.execute(
            """
            UPDATE app_state
            SET revision = revision + 1, updated_at = ?
            WHERE singleton_id = 1
            """,
            (now,),
        )

    def _load_stage(self, conn: sqlite3.Connection) -> Stage:
        row = conn.execute(
            "SELECT stage FROM app_state WHERE singleton_id = 1"
        ).fetchone()
        if row is None:
            raise NotFound("app_state")
        return Stage(row[0])

    def _require_stage(
        self, conn: sqlite3.Connection, allowed: set[Stage]
    ) -> Stage:
        stage = self._load_stage(conn)
        if stage not in allowed:
            raise InvariantViolation(
                f"stage {stage.value} not in {[s.value for s in allowed]}"
            )
        return stage

    def _set_stage(
        self, conn: sqlite3.Connection, stage: Stage, now: datetime
    ) -> None:
        conn.execute(
            "UPDATE app_state SET stage = ?, updated_at = ? WHERE singleton_id = 1",
            (stage.value, sql.dt(now)),
        )

    def _upsert_profile(
        self, conn: sqlite3.Connection, profile: Profile, *, now: datetime
    ) -> None:
        conn.execute(
            """
            UPDATE profile
            SET name = ?, primary_language = ?, date_of_birth = ?, notes = ?, updated_at = ?
            WHERE singleton_id = 1
            """,
            (
                profile.name,
                profile.primary_language,
                sql.date_iso(profile.date_of_birth),
                profile.notes,
                sql.dt(now),
            ),
        )

    def _require_open_session(
        self, conn: sqlite3.Connection, session_id: UUID
    ) -> Session:
        row = conn.execute(
            """
            SELECT id, kind, plan_id, started_at, ended_at, summary, briefing_json
            FROM sessions WHERE id = ? AND ended_at IS NULL
            """,
            (str(session_id),),
        ).fetchone()
        if row is None:
            raise NotFound(f"active session {session_id}")
        return sql.row_to_session(row)

    def _next_sequence(self, conn: sqlite3.Connection, session_id: UUID) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE session_id = ?",
            (str(session_id),),
        ).fetchone()
        return int(row[0])

    def _load_plan(self, conn: sqlite3.Connection, plan_id: UUID) -> Plan:
        row = conn.execute(
            """
            SELECT id, version, selected_style, focus, themes_json, goals_json,
                   current_progress, planned_interventions_json,
                   revision_recommendations_json, session_briefing_json,
                   source_session_id, supersedes_plan_id, created_at
            FROM plans WHERE id = ?
            """,
            (str(plan_id),),
        ).fetchone()
        if row is None:
            raise NotFound(f"plan {plan_id}")
        return sql.row_to_plan(row)

    def _load_operation(self, conn: sqlite3.Connection, operation_id: UUID) -> Operation:
        row = conn.execute(
            """
            SELECT id, kind, status, source_session_id, attempt, result_json,
                   error_code, error_message, retryable, created_at, updated_at,
                   started_at, completed_at
            FROM operations WHERE id = ?
            """,
            (str(operation_id),),
        ).fetchone()
        if row is None:
            raise NotFound(f"operation {operation_id}")
        return sql.row_to_operation(row)

    def _load_chat_turn(self, conn: sqlite3.Connection, turn_id: UUID) -> ChatTurn:
        row = conn.execute(
            """
            SELECT id, session_id, client_message_id, status, user_message_id,
                   assistant_message_id, error_code, error_message, retryable,
                   created_at, updated_at, completed_at
            FROM chat_turns WHERE id = ?
            """,
            (str(turn_id),),
        ).fetchone()
        if row is None:
            raise NotFound(f"chat turn {turn_id}")
        return sql.row_to_chat_turn(row)

    def _load_snapshot_facts(self, conn: sqlite3.Connection) -> WorkflowFacts:
        stage = self._load_stage(conn)
        profile_row = conn.execute(
            "SELECT name, primary_language FROM profile WHERE singleton_id = 1"
        ).fetchone()
        profile = Profile(
            name=profile_row[0],
            primary_language=profile_row[1],
        ) if profile_row else Profile(name="", primary_language="")
        active_session = conn.execute(
            "SELECT 1 FROM sessions WHERE ended_at IS NULL LIMIT 1"
        ).fetchone()
        op_row = conn.execute(
            """
            SELECT kind, status FROM operations
            WHERE status IN ('pending', 'running', 'failed')
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        turn_row = conn.execute(
            "SELECT status FROM chat_turns WHERE status = 'pending' LIMIT 1"
        ).fetchone()
        return WorkflowFacts(
            stage=stage,
            profile_complete=is_profile_complete(profile),
            has_active_session=active_session is not None,
            operation_kind=OperationKind(op_row[0]) if op_row else None,
            operation_status=OperationStatus(op_row[1]) if op_row else None,
            chat_turn_status=ChatTurnStatus(turn_row[0]) if turn_row else None,
        )
