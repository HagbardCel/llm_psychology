"""Concrete SQLite persistence for the target single-user core."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID

from pydantic import ValidationError

from jung.domain.errors import (
    Busy,
    InvariantViolation,
    NotFound,
    PersistenceFailure,
)
from jung.domain.models import (
    Message,
    MessageRole,
    NewPlanRevision,
    Operation,
    OperationKind,
    OperationStatus,
    Plan,
    PlanContent,
    Profile,
    Session,
    SessionKind,
    Stage,
    StoredProfile,
    WorkflowFacts,
    is_profile_complete,
)
from jung.persistence import _sqlite_support as sql
from jung.workflow import derive_stage

SCHEMA_VERSION = sql.SCHEMA_VERSION
_T = TypeVar("_T")


def _build_plan(**values: object) -> Plan:
    try:
        return Plan.model_validate(values, strict=True)
    except ValidationError as exc:
        raise InvariantViolation("invalid plan payload") from exc


def _derived_profiles_equal(
    existing: dict[str, Any] | None,
    updated: dict[str, Any] | None,
) -> bool:
    if existing is None and updated is None:
        return True
    if existing is None or updated is None:
        return False
    existing_normalized = sql.validate_json_mapping(
        existing, field_name="derived_profile"
    )
    updated_normalized = sql.validate_json_mapping(
        updated, field_name="derived_profile"
    )
    return existing_normalized == updated_normalized


_SESSION_SELECT = """
    SELECT id, kind, plan_id, started_at, ended_at, summary, briefing_json,
           intake_record_json
    FROM sessions
"""


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
                if sql.has_any_user_table(conn):
                    raise PersistenceFailure(
                        "database has unexpected tables without schema version; "
                        "reset the database"
                    )
                try:
                    sql.create_schema(conn)
                    sql.seed_initial_state(conn)
                    sql.assert_foreign_keys(conn)
                    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                    conn.commit()
                except sqlite3.Error as exc:
                    if conn.in_transaction:
                        conn.rollback()
                    raise sql.translate_sqlite_error(exc) from exc
                except Exception:
                    if conn.in_transaction:
                        conn.rollback()
                    raise
                return
            if version != SCHEMA_VERSION:
                raise PersistenceFailure(
                    f"unsupported schema version {version}; reset the database"
                )

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
                f"{_SESSION_SELECT} ORDER BY started_at DESC"
            ).fetchall()
            return [sql.row_to_session(row) for row in rows]

    def get_session(self, session_id: UUID) -> Session | None:
        with self._connect() as conn:
            row = conn.execute(
                f"{_SESSION_SELECT} WHERE id = ?",
                (str(session_id),),
            ).fetchone()
            return sql.row_to_session(row) if row else None

    def list_messages(self, session_id: UUID) -> list[Message]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, sequence, role, content, client_message_id,
                       created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY sequence ASC
                """,
                (str(session_id),),
            ).fetchall()
            return [sql.row_to_message(row) for row in rows]

    def get_messages_by_client_id(
        self, session_id: UUID, client_message_id: UUID
    ) -> tuple[Message | None, Message | None]:
        with self._connect() as conn:
            return self._load_messages_by_client_id(conn, session_id, client_message_id)

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

    def get_active_session(self) -> Session | None:
        with self._connect() as conn:
            row = conn.execute(
                f"{_SESSION_SELECT} WHERE ended_at IS NULL LIMIT 1"
            ).fetchone()
            return sql.row_to_session(row) if row else None

    def load_snapshot_facts(self) -> WorkflowFacts:
        with self._connect() as conn:
            return self._load_snapshot_facts(conn)

    def update_profile(
        self,
        profile: Profile,
        *,
        intake_session_id: UUID | None,
        now: datetime,
    ) -> None:
        def mutate(conn: sqlite3.Connection) -> None:
            stage = self._require_stage(conn, {Stage.SETUP, Stage.INTAKE})
            profile_complete = is_profile_complete(profile)
            if stage == Stage.INTAKE:
                if not profile_complete:
                    raise InvariantViolation(
                        "profile must remain complete during intake"
                    )
                if intake_session_id is not None:
                    raise InvariantViolation(
                        "intake_session_id must be None during intake"
                    )
                self._upsert_profile(conn, profile, now=now)
                return

            self._upsert_profile(conn, profile, now=now)
            if profile_complete:
                if intake_session_id is None:
                    raise InvariantViolation(
                        "intake_session_id is required when profile becomes complete"
                    )
                if conn.execute(
                    "SELECT 1 FROM sessions WHERE ended_at IS NULL LIMIT 1"
                ).fetchone():
                    raise InvariantViolation("open session already exists")
                conn.execute(
                    """
                    INSERT INTO sessions (
                        id, kind, plan_id, started_at, ended_at, summary,
                        briefing_json, intake_record_json
                    ) VALUES (?, ?, NULL, ?, NULL, NULL, NULL, NULL)
                    """,
                    (
                        str(intake_session_id),
                        SessionKind.INTAKE.value,
                        sql.dt(now),
                    ),
                )
            elif intake_session_id is not None:
                raise InvariantViolation(
                    "intake_session_id must be None while profile remains incomplete"
                )

        self._write(mutate)

    def get_latest_completed_operation(self, kind: OperationKind) -> Operation | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, kind, status, source_session_id, attempt, result_json,
                       error_code, error_message, retryable, created_at, updated_at,
                       started_at, completed_at
                FROM operations
                WHERE kind = ? AND status = ?
                ORDER BY completed_at DESC
                LIMIT 1
                """,
                (kind.value, OperationStatus.COMPLETE.value),
            ).fetchone()
            return sql.row_to_operation(row) if row else None

    def list_plans_for_session(self, session_id: UUID) -> list[Plan]:
        with self._connect() as conn:
            session_row = conn.execute(
                "SELECT plan_id FROM sessions WHERE id = ?",
                (str(session_id),),
            ).fetchone()
            if session_row is None:
                raise NotFound(f"session {session_id}")
            plan_ids: list[str] = []
            if session_row[0]:
                plan_ids.append(session_row[0])
            rows = conn.execute(
                """
                SELECT id FROM plans
                WHERE source_session_id = ?
                ORDER BY version ASC, created_at ASC, id ASC
                """,
                (str(session_id),),
            ).fetchall()
            for row in rows:
                if row[0] not in plan_ids:
                    plan_ids.append(row[0])
            if not plan_ids:
                return []
            placeholders = ",".join("?" for _ in plan_ids)
            plan_rows = conn.execute(
                f"""
                SELECT id, version, selected_style, focus, themes_json, goals_json,
                       current_progress, planned_interventions_json,
                       revision_recommendations_json, session_briefing_json,
                       source_session_id, supersedes_plan_id, created_at
                FROM plans
                WHERE id IN ({placeholders})
                ORDER BY version ASC, created_at ASC, id ASC
                """,
                plan_ids,
            ).fetchall()
            return [sql.row_to_plan(row) for row in plan_rows]

    def append_user_message(
        self,
        *,
        session_id: UUID,
        client_message_id: UUID,
        user_message_id: UUID,
        content: str,
        now: datetime,
    ) -> Message:
        def mutate(conn: sqlite3.Connection) -> Message:
            stage = self._require_stage(conn, {Stage.INTAKE, Stage.THERAPY})
            session = self._require_open_session(conn, session_id)
            if stage == Stage.INTAKE and session.kind != SessionKind.INTAKE:
                raise InvariantViolation("intake chat requires intake session")
            if stage == Stage.THERAPY and session.kind != SessionKind.THERAPY:
                raise InvariantViolation("therapy chat requires therapy session")
            latest = self._latest_message(conn, session_id)
            if latest is not None and latest.role is MessageRole.USER:
                raise InvariantViolation(
                    "unanswered user message must be retried before sending another"
                )
            existing_user, _existing_assistant = self._load_messages_by_client_id(
                conn, session_id, client_message_id
            )
            if existing_user is not None:
                raise InvariantViolation(
                    "user message already exists for client_message_id"
                )
            sequence = self._next_sequence(conn, session_id)
            created_at = sql.dt(now)
            conn.execute(
                """
                INSERT INTO messages (
                    id, session_id, sequence, role, content, client_message_id,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(user_message_id),
                    str(session_id),
                    sequence,
                    MessageRole.USER.value,
                    content,
                    str(client_message_id),
                    created_at,
                ),
            )
            return Message(
                id=user_message_id,
                session_id=session_id,
                sequence=sequence,
                role=MessageRole.USER,
                content=content,
                client_message_id=client_message_id,
                created_at=sql.parse_dt(created_at),
            )

        return self._write(mutate)

    def complete_chat_response(
        self,
        *,
        session_id: UUID,
        client_message_id: UUID,
        assistant_message_id: UUID,
        content: str,
        intake_record: dict[str, Any] | None = None,
        now: datetime,
    ) -> Message:
        validated_intake_record: dict[str, Any] | None = None
        if intake_record is not None:
            validated_intake_record = sql.validate_json_mapping(
                intake_record, field_name="intake_record"
            )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                message = self._insert_assistant_response(
                    conn,
                    session_id=session_id,
                    client_message_id=client_message_id,
                    assistant_message_id=assistant_message_id,
                    content=content,
                    now=now,
                )
                if validated_intake_record is not None:
                    session_row = conn.execute(
                        f"{_SESSION_SELECT} WHERE id = ?",
                        (str(session_id),),
                    ).fetchone()
                    if session_row is None:
                        raise NotFound(f"session {session_id}")
                    if SessionKind(session_row[1]) is not SessionKind.INTAKE:
                        raise InvariantViolation(
                            "intake_record is only allowed for intake sessions"
                        )
                    conn.execute(
                        """
                        UPDATE sessions
                        SET intake_record_json = ?
                        WHERE id = ?
                        """,
                        (
                            sql.json_dumps(validated_intake_record),
                            str(session_id),
                        ),
                    )
                conn.commit()
                return message
            except Exception as exc:
                conn.rollback()
                raise sql.translate_sqlite_error(exc) from exc

    def complete_final_intake_response(
        self,
        *,
        session_id: UUID,
        client_message_id: UUID,
        assistant_message_id: UUID,
        content: str,
        intake_record: dict[str, Any],
        operation_id: UUID,
        now: datetime,
    ) -> tuple[Message, Operation]:
        validated_intake_record = sql.validate_json_mapping(
            intake_record, field_name="intake_record"
        )

        def mutate(conn: sqlite3.Connection) -> tuple[Message, Operation]:
            session_row = conn.execute(
                f"{_SESSION_SELECT} WHERE id = ?",
                (str(session_id),),
            ).fetchone()
            if session_row is None:
                raise NotFound(f"session {session_id}")
            if SessionKind(session_row[1]) is not SessionKind.INTAKE:
                raise InvariantViolation("final intake requires intake session")
            self._require_stage(conn, {Stage.INTAKE})
            message = self._insert_assistant_response(
                conn,
                session_id=session_id,
                client_message_id=client_message_id,
                assistant_message_id=assistant_message_id,
                content=content,
                now=now,
            )
            conn.execute(
                """
                UPDATE sessions
                SET intake_record_json = ?, ended_at = ?
                WHERE id = ?
                """,
                (
                    sql.json_dumps(validated_intake_record),
                    sql.dt(now),
                    str(session_id),
                ),
            )
            existing = self._find_operation_by_source(
                conn, OperationKind.ASSESSMENT, session_id
            )
            if existing is not None:
                operation = existing
            else:
                operation = self._insert_pending_operation(
                    conn,
                    kind=OperationKind.ASSESSMENT,
                    source_session_id=session_id,
                    operation_id=operation_id,
                    now=now,
                )
            return message, operation

        return self._write(mutate)

    def mark_operation_running(
        self,
        operation_id: UUID,
        *,
        now: datetime,
    ) -> Operation:
        def mutate(conn: sqlite3.Connection) -> Operation:
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
            return self._load_operation(conn, operation_id)

        return self._write(mutate)

    def complete_assessment(
        self,
        operation_id: UUID,
        *,
        result: dict[str, Any],
        now: datetime,
    ) -> Stage:
        validated_result = sql.validate_json_mapping(result, field_name="result")

        def mutate(conn: sqlite3.Connection) -> Stage:
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
                    sql.json_dumps(validated_result),
                    sql.dt(now),
                    sql.dt(now),
                    str(operation_id),
                    OperationStatus.RUNNING.value,
                    OperationKind.ASSESSMENT.value,
                ),
            )
            self._ensure_operation_updated(conn, cursor, operation_id)
            stage = self._load_snapshot_facts(conn).stage
            if stage is not Stage.STYLE_SELECTION:
                raise InvariantViolation(
                    f"assessment completion must yield style_selection, got {stage.value}"
                )
            return stage

        return self._write(mutate)

    def fail_operation(
        self,
        operation_id: UUID,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
        now: datetime,
    ) -> Operation:
        def mutate(conn: sqlite3.Connection) -> Operation:
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
            return self._load_operation(conn, operation_id)

        return self._write(mutate)

    def retry_operation(
        self,
        operation_id: UUID,
        *,
        now: datetime,
    ) -> Operation:
        def mutate(conn: sqlite3.Connection) -> Operation:
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
            return self._load_operation(conn, operation_id)

        return self._write(mutate)

    def select_style_and_create_initial_plan(
        self,
        *,
        style_id: str,
        plan_id: UUID,
        content: PlanContent,
        intake_session_id: UUID,
        now: datetime,
    ) -> None:
        plan = _build_plan(
            id=plan_id,
            version=1,
            selected_style=style_id,
            **content.model_dump(),
            session_briefing=None,
            source_session_id=intake_session_id,
            supersedes_plan_id=None,
            created_at=now,
        )

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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)
                """,
                (
                    str(plan.id),
                    plan.version,
                    plan.selected_style,
                    plan.focus,
                    sql.json_dumps(plan.themes),
                    sql.json_dumps(plan.goals),
                    plan.current_progress,
                    sql.json_dumps(plan.planned_interventions),
                    sql.json_dumps(plan.revision_recommendations),
                    str(plan.source_session_id),
                    sql.dt(plan.created_at),
                ),
            )
            conn.execute(
                "UPDATE profile SET current_plan_id = ?, updated_at = ? WHERE singleton_id = 1",
                (str(plan.id), sql.dt(now)),
            )

        self._write(mutate)

    def start_therapy_session(
        self,
        *,
        session_id: UUID,
        now: datetime,
    ) -> Session:
        def mutate(conn: sqlite3.Connection) -> Session:
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
                INSERT INTO sessions (
                    id, kind, plan_id, started_at, ended_at, summary, briefing_json,
                    intake_record_json
                )
                VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL)
                """,
                (
                    str(session_id),
                    SessionKind.THERAPY.value,
                    plan_row[0],
                    sql.dt(now),
                ),
            )
            row = conn.execute(
                f"{_SESSION_SELECT} WHERE id = ?",
                (str(session_id),),
            ).fetchone()
            return sql.row_to_session(row)

        return self._write(mutate)

    def end_therapy_session(
        self,
        *,
        session_id: UUID,
        operation_id: UUID,
        now: datetime,
    ) -> Operation:
        def mutate(conn: sqlite3.Connection) -> Operation:
            existing = self._find_operation_by_source(
                conn, OperationKind.POST_SESSION, session_id
            )
            if existing is not None:
                return existing

            self._require_stage(conn, {Stage.THERAPY})
            session = self._require_open_session(conn, session_id)
            if session.kind != SessionKind.THERAPY:
                raise InvariantViolation("session must be therapy")
            conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?",
                (sql.dt(now), str(session_id)),
            )
            return self._insert_pending_operation(
                conn,
                kind=OperationKind.POST_SESSION,
                source_session_id=session_id,
                operation_id=operation_id,
                now=now,
            )

        return self._write(mutate)

    def complete_post_session(
        self,
        operation_id: UUID,
        *,
        summary: str,
        briefing: dict[str, Any],
        derived_profile: dict[str, Any] | None,
        new_plan: NewPlanRevision | None,
        now: datetime,
    ) -> Stage:
        validated_briefing = sql.validate_json_mapping(briefing, field_name="briefing")
        validated_profile: dict[str, Any] | None = None
        if derived_profile is not None:
            validated_profile = sql.validate_json_mapping(
                derived_profile, field_name="derived_profile"
            )

        def mutate(conn: sqlite3.Connection) -> Stage:
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
            source_session_id = UUID(op_row[2])
            current_plan = self._require_current_plan(conn)
            profile_row = conn.execute(
                "SELECT derived_profile_json, current_plan_id, updated_at "
                "FROM profile WHERE singleton_id = 1"
            ).fetchone()
            existing_profile = (
                sql.json_loads(profile_row[0])
                if profile_row and profile_row[0]
                else None
            )
            profile_changed = not _derived_profiles_equal(
                existing_profile, validated_profile
            )
            plan_changed = new_plan is not None

            conn.execute(
                """
                UPDATE sessions
                SET summary = ?, briefing_json = ?
                WHERE id = ?
                """,
                (summary, sql.json_dumps(validated_briefing), str(source_session_id)),
            )

            result_plan_id: str | None = None
            result_plan_version: int | None = None
            current_plan_id = str(current_plan.id)

            if new_plan is not None:
                plan = _build_plan(
                    id=new_plan.plan_id,
                    version=current_plan.version + 1,
                    selected_style=current_plan.selected_style,
                    **new_plan.content.model_dump(),
                    session_briefing=validated_briefing,
                    source_session_id=source_session_id,
                    supersedes_plan_id=current_plan.id,
                    created_at=now,
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
                        str(plan.id),
                        plan.version,
                        plan.selected_style,
                        plan.focus,
                        sql.json_dumps(plan.themes),
                        sql.json_dumps(plan.goals),
                        plan.current_progress,
                        sql.json_dumps(plan.planned_interventions),
                        sql.json_dumps(plan.revision_recommendations),
                        sql.json_dumps(plan.session_briefing),
                        str(plan.source_session_id),
                        str(plan.supersedes_plan_id),
                        sql.dt(plan.created_at),
                    ),
                )
                result_plan_id = str(plan.id)
                result_plan_version = plan.version
                current_plan_id = str(plan.id)

            if profile_changed or plan_changed:
                if profile_changed and plan_changed:
                    conn.execute(
                        """
                        UPDATE profile
                        SET derived_profile_json = ?, current_plan_id = ?, updated_at = ?
                        WHERE singleton_id = 1
                        """,
                        (
                            sql.json_dumps(validated_profile),
                            current_plan_id,
                            sql.dt(now),
                        ),
                    )
                elif profile_changed:
                    conn.execute(
                        """
                        UPDATE profile
                        SET derived_profile_json = ?, updated_at = ?
                        WHERE singleton_id = 1
                        """,
                        (
                            sql.json_dumps(validated_profile),
                            sql.dt(now),
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE profile
                        SET current_plan_id = ?, updated_at = ?
                        WHERE singleton_id = 1
                        """,
                        (current_plan_id, sql.dt(now)),
                    )
            result = {
                "plan_id": result_plan_id,
                "plan_version": result_plan_version,
                "profile_changed": profile_changed,
            }
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
            stage = self._load_snapshot_facts(conn).stage
            if stage is not Stage.READY:
                raise InvariantViolation(
                    f"post-session completion must yield ready, got {stage.value}"
                )
            return stage

        return self._write(mutate)

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
                recovered = [self._load_operation(conn, UUID(row[0])) for row in rows]
                conn.commit()
                return recovered
            except Exception as exc:
                conn.rollback()
                raise sql.translate_sqlite_error(exc) from exc

    def _write(
        self,
        mutate: Callable[[sqlite3.Connection], _T],
    ) -> _T:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = mutate(conn)
                conn.commit()
                return result
            except Exception as exc:
                conn.rollback()
                translated = sql.translate_sqlite_error(exc)
                if translated is exc:
                    raise
                raise translated from exc

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

    def _find_operation_by_source(
        self,
        conn: sqlite3.Connection,
        kind: OperationKind,
        source_session_id: UUID,
    ) -> Operation | None:
        row = conn.execute(
            """
            SELECT id FROM operations
            WHERE kind = ? AND source_session_id = ?
            """,
            (kind.value, str(source_session_id)),
        ).fetchone()
        if row is None:
            return None
        return self._load_operation(conn, UUID(row[0]))

    def _insert_pending_operation(
        self,
        conn: sqlite3.Connection,
        *,
        kind: OperationKind,
        source_session_id: UUID,
        operation_id: UUID,
        now: datetime,
    ) -> Operation:
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
                kind.value,
                OperationStatus.PENDING.value,
                str(source_session_id),
                sql.dt(now),
                sql.dt(now),
            ),
        )
        return self._load_operation(conn, operation_id)

    def _require_stage(self, conn: sqlite3.Connection, allowed: set[Stage]) -> Stage:
        stage = self._load_snapshot_facts(conn).stage
        if stage not in allowed:
            raise InvariantViolation(
                f"stage {stage.value} not in {[s.value for s in allowed]}"
            )
        return stage

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
            f"{_SESSION_SELECT} WHERE id = ? AND ended_at IS NULL",
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

    def _load_operation(
        self, conn: sqlite3.Connection, operation_id: UUID
    ) -> Operation:
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

    def _load_snapshot_facts(self, conn: sqlite3.Connection) -> WorkflowFacts:
        profile_row = conn.execute(
            """
            SELECT name, primary_language, current_plan_id
            FROM profile WHERE singleton_id = 1
            """
        ).fetchone()
        if profile_row is None:
            raise InvariantViolation("profile singleton is missing")
        profile = Profile(
            name=profile_row[0],
            primary_language=profile_row[1],
        )
        current_plan_id = UUID(profile_row[2]) if profile_row[2] else None
        has_any_plan = (
            conn.execute("SELECT 1 FROM plans LIMIT 1").fetchone() is not None
        )
        active_row = conn.execute(
            f"{_SESSION_SELECT} WHERE ended_at IS NULL LIMIT 1"
        ).fetchone()
        active_session = sql.row_to_session(active_row) if active_row else None
        op_row = conn.execute(
            """
            SELECT id, kind, status, source_session_id, attempt, result_json,
                   error_code, error_message, retryable, created_at, updated_at,
                   started_at, completed_at
            FROM operations
            WHERE status IN ('pending', 'running', 'failed')
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        current_operation = sql.row_to_operation(op_row) if op_row else None
        operation_source_session: Session | None = None
        if current_operation is not None:
            source_row = conn.execute(
                f"{_SESSION_SELECT} WHERE id = ?",
                (str(current_operation.source_session_id),),
            ).fetchone()
            if source_row is None:
                raise InvariantViolation(
                    "current operation is missing its source session"
                )
            operation_source_session = sql.row_to_session(source_row)
        completed_assessment = conn.execute(
            """
            SELECT 1 FROM operations
            WHERE kind = ? AND status = ?
            LIMIT 1
            """,
            (OperationKind.ASSESSMENT.value, OperationStatus.COMPLETE.value),
        ).fetchone()
        stage = derive_stage(
            profile_complete=is_profile_complete(profile),
            active_session=active_session,
            current_plan_id=current_plan_id,
            has_any_plan=has_any_plan,
            current_operation=current_operation,
            operation_source_session=operation_source_session,
            has_completed_assessment=completed_assessment is not None,
        )
        return WorkflowFacts(
            stage=stage,
            profile_complete=is_profile_complete(profile),
            operation_kind=current_operation.kind if current_operation else None,
            operation_status=current_operation.status if current_operation else None,
            operation_retryable=(
                current_operation.retryable if current_operation else None
            ),
        )

    def _load_messages_by_client_id(
        self,
        conn: sqlite3.Connection,
        session_id: UUID,
        client_message_id: UUID,
    ) -> tuple[Message | None, Message | None]:
        rows = conn.execute(
            """
            SELECT id, session_id, sequence, role, content, client_message_id, created_at
            FROM messages
            WHERE session_id = ? AND client_message_id = ?
            """,
            (str(session_id), str(client_message_id)),
        ).fetchall()
        user: Message | None = None
        assistant: Message | None = None
        for row in rows:
            message = sql.row_to_message(row)
            if message.role is MessageRole.USER:
                if user is not None:
                    raise InvariantViolation(
                        "duplicate user message for client_message_id"
                    )
                user = message
            elif message.role is MessageRole.ASSISTANT:
                if assistant is not None:
                    raise InvariantViolation(
                        "duplicate assistant message for client_message_id"
                    )
                assistant = message
        return user, assistant

    def _latest_message(
        self, conn: sqlite3.Connection, session_id: UUID
    ) -> Message | None:
        row = conn.execute(
            """
            SELECT id, session_id, sequence, role, content, client_message_id, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (str(session_id),),
        ).fetchone()
        return sql.row_to_message(row) if row else None

    def _insert_assistant_response(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: UUID,
        client_message_id: UUID,
        assistant_message_id: UUID,
        content: str,
        now: datetime,
    ) -> Message:
        user, assistant = self._load_messages_by_client_id(
            conn, session_id, client_message_id
        )
        if user is None:
            raise NotFound(f"user message {client_message_id} for session {session_id}")
        if assistant is not None:
            raise InvariantViolation(
                "assistant message already exists for client_message_id"
            )
        latest = self._latest_message(conn, session_id)
        if latest is None or latest.id != user.id:
            raise InvariantViolation(
                "assistant response requires unanswered latest user message"
            )
        if latest.client_message_id != client_message_id:
            raise InvariantViolation("client_message_id mismatch for latest user")
        sequence = self._next_sequence(conn, session_id)
        created_at = sql.dt(now)
        conn.execute(
            """
            INSERT INTO messages (
                id, session_id, sequence, role, content, client_message_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(assistant_message_id),
                str(session_id),
                sequence,
                MessageRole.ASSISTANT.value,
                content,
                str(client_message_id),
                created_at,
            ),
        )
        return Message(
            id=assistant_message_id,
            session_id=session_id,
            sequence=sequence,
            role=MessageRole.ASSISTANT,
            content=content,
            client_message_id=client_message_id,
            created_at=sql.parse_dt(created_at),
        )
