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
from jung.domain.session_artifacts import SessionReview
from jung.persistence import _sqlite_support as sql
from jung.workflow import derive_stage

SCHEMA_VERSION = sql.SCHEMA_VERSION
_T = TypeVar("_T")


def _build_plan(**values: object) -> Plan:
    try:
        return Plan.model_validate(values, strict=True)
    except ValidationError as exc:
        raise InvariantViolation("invalid plan payload") from exc


_SESSION_SELECT = """
    SELECT id, kind, plan_id, started_at, ended_at, intake_record_json, review_json
    FROM sessions
"""

_PLAN_COLUMNS = """
    id, version, selected_style, focus, themes_json, goals_json,
    current_progress, planned_interventions_json,
    revision_recommendations_json,
    source_session_id, supersedes_plan_id, created_at
"""

_PLAN_SELECT = f"""
    SELECT {_PLAN_COLUMNS.strip()}
    FROM plans
"""

_CURRENT_PLAN_SELECT = """
    SELECT p.id, p.version, p.selected_style, p.focus, p.themes_json,
           p.goals_json, p.current_progress, p.planned_interventions_json,
           p.revision_recommendations_json,
           p.source_session_id, p.supersedes_plan_id, p.created_at
    FROM profile pr
    JOIN plans p ON p.id = pr.current_plan_id
    WHERE pr.singleton_id = 1
"""

_OPERATION_SELECT = """
    SELECT id, kind, status, source_session_id, attempt, result_json,
           error_code, error_message, retryable, created_at, updated_at,
           started_at, completed_at
    FROM operations
"""

_MESSAGE_SELECT = """
    SELECT id, session_id, sequence, role, content, client_message_id, created_at
    FROM messages
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
                       current_plan_id, created_at, updated_at
                FROM profile WHERE singleton_id = 1
                """
            ).fetchone()
            if row is None:
                return None
            return sql.row_to_stored_profile(row)

    def get_current_plan(self) -> Plan | None:
        with self._connect() as conn:
            return self._load_current_plan(conn)

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
                f"""
                {_MESSAGE_SELECT}
                WHERE session_id = ?
                ORDER BY sequence ASC
                """,
                (str(session_id),),
            ).fetchall()
            return [sql.row_to_message(row) for row in rows]

    def list_grounded_patient_messages(self) -> list[Message]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.id, m.session_id, m.sequence, m.role, m.content,
                       m.client_message_id, m.created_at
                FROM grounded_patient_turns g
                JOIN messages m ON m.id = g.message_id
                JOIN sessions s ON s.id = m.session_id
                ORDER BY s.started_at ASC, s.id ASC, m.sequence ASC
                """
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
                f"""
                {_OPERATION_SELECT}
                WHERE status IN ('pending', 'running', 'failed')
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            return sql.row_to_operation(row) if row else None

    def get_operation(self, operation_id: UUID) -> Operation | None:
        with self._connect() as conn:
            row = conn.execute(
                f"{_OPERATION_SELECT} WHERE id = ?",
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
                        id, kind, plan_id, started_at, ended_at,
                        intake_record_json, review_json
                    ) VALUES (?, ?, NULL, ?, NULL, NULL, NULL)
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
                f"""
                {_OPERATION_SELECT}
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
            return [self._load_plan(conn, UUID(plan_id)) for plan_id in plan_ids]

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

        def mutate(conn: sqlite3.Connection) -> Message:
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
            return message

        return self._write(mutate)

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
            self._complete_running_operation(
                conn,
                operation_id,
                kind=OperationKind.ASSESSMENT,
                result=validated_result,
                now=now,
            )
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
            self._insert_plan(conn, plan)
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
                    id, kind, plan_id, started_at, ended_at,
                    intake_record_json, review_json
                )
                VALUES (?, ?, ?, ?, NULL, NULL, NULL)
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
        review: SessionReview,
        new_plan: NewPlanRevision | None,
        now: datetime,
    ) -> Stage:
        review_json = sql.json_dumps(review.model_dump(mode="json"))

        def mutate(conn: sqlite3.Connection) -> Stage:
            self._require_stage(conn, {Stage.POST_SESSION})
            operation = self._load_operation(conn, operation_id)
            if operation.kind is not OperationKind.POST_SESSION:
                raise InvariantViolation("operation must be post_session")
            if operation.status is not OperationStatus.RUNNING:
                raise InvariantViolation("operation must be running")
            source_session_id = operation.source_session_id
            current_plan = self._require_current_plan(conn)

            citations = review.analysis.patient_turn_citations
            sequences = tuple(item.patient_sequence for item in citations)
            if len(sequences) != len(set(sequences)):
                raise InvariantViolation(
                    "patient turn citation sequences must be unique"
                )

            grounded_message_ids: list[UUID] = []
            for sequence in sequences:
                row = conn.execute(
                    """
                    SELECT id, role
                    FROM messages
                    WHERE session_id = ? AND sequence = ?
                    """,
                    (str(source_session_id), sequence),
                ).fetchone()
                if row is None:
                    raise InvariantViolation(
                        f"patient turn citation sequence {sequence} "
                        "does not exist in the source session"
                    )
                message_id, role = UUID(row[0]), row[1]
                if role != MessageRole.USER.value:
                    raise InvariantViolation(
                        f"patient turn citation sequence {sequence} "
                        "must identify a user message"
                    )
                grounded_message_ids.append(message_id)

            conn.execute(
                """
                UPDATE sessions
                SET review_json = ?
                WHERE id = ?
                """,
                (review_json, str(source_session_id)),
            )

            for message_id in grounded_message_ids:
                conn.execute(
                    """
                    INSERT INTO grounded_patient_turns (message_id)
                    VALUES (?)
                    """,
                    (str(message_id),),
                )

            result_plan_id: str | None = None
            result_plan_version: int | None = None

            if new_plan is not None:
                plan = _build_plan(
                    id=new_plan.plan_id,
                    version=current_plan.version + 1,
                    selected_style=current_plan.selected_style,
                    **new_plan.content.model_dump(),
                    source_session_id=source_session_id,
                    supersedes_plan_id=current_plan.id,
                    created_at=now,
                )
                self._insert_plan(conn, plan)
                result_plan_id = str(plan.id)
                result_plan_version = plan.version
                conn.execute(
                    """
                    UPDATE profile
                    SET current_plan_id = ?, updated_at = ?
                    WHERE singleton_id = 1
                    """,
                    (str(plan.id), sql.dt(now)),
                )

            result = {
                "plan_id": result_plan_id,
                "plan_version": result_plan_version,
            }
            self._complete_running_operation(
                conn,
                operation_id,
                kind=OperationKind.POST_SESSION,
                result=result,
                now=now,
            )
            stage = self._load_snapshot_facts(conn).stage
            if stage is not Stage.READY:
                raise InvariantViolation(
                    f"post-session completion must yield ready, got {stage.value}"
                )
            return stage

        return self._write(mutate)

    def recover_stale_operation(self, *, now: datetime) -> Operation | None:
        def mutate(conn: sqlite3.Connection) -> Operation | None:
            row = conn.execute(
                """
                SELECT id FROM operations WHERE status = ?
                """,
                (OperationStatus.RUNNING.value,),
            ).fetchone()
            if row is None:
                return None
            operation_id = UUID(row[0])
            conn.execute(
                """
                UPDATE operations
                SET status = ?, started_at = NULL, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    OperationStatus.PENDING.value,
                    sql.dt(now),
                    str(operation_id),
                    OperationStatus.RUNNING.value,
                ),
            )
            return self._load_operation(conn, operation_id)

        return self._write(mutate)

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

    def _load_current_plan(self, conn: sqlite3.Connection) -> Plan | None:
        row = conn.execute(_CURRENT_PLAN_SELECT).fetchone()
        return sql.row_to_plan(row) if row else None

    def _require_current_plan(self, conn: sqlite3.Connection) -> Plan:
        plan = self._load_current_plan(conn)
        if plan is None:
            raise InvariantViolation("current plan is required")
        return plan

    def _find_operation_by_source(
        self,
        conn: sqlite3.Connection,
        kind: OperationKind,
        source_session_id: UUID,
    ) -> Operation | None:
        row = conn.execute(
            f"""
            {_OPERATION_SELECT}
            WHERE kind = ? AND source_session_id = ?
            """,
            (kind.value, str(source_session_id)),
        ).fetchone()
        return sql.row_to_operation(row) if row else None

    def _insert_plan(self, conn: sqlite3.Connection, plan: Plan) -> None:
        source_session_id = (
            str(plan.source_session_id) if plan.source_session_id is not None else None
        )
        supersedes_plan_id = (
            str(plan.supersedes_plan_id)
            if plan.supersedes_plan_id is not None
            else None
        )
        conn.execute(
            """
            INSERT INTO plans (
                id, version, selected_style, focus, themes_json, goals_json,
                current_progress, planned_interventions_json,
                revision_recommendations_json,
                source_session_id, supersedes_plan_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                source_session_id,
                supersedes_plan_id,
                sql.dt(plan.created_at),
            ),
        )

    def _complete_running_operation(
        self,
        conn: sqlite3.Connection,
        operation_id: UUID,
        *,
        kind: OperationKind,
        result: dict[str, Any],
        now: datetime,
    ) -> None:
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
                kind.value,
            ),
        )
        self._ensure_operation_updated(conn, cursor, operation_id)

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
            f"{_PLAN_SELECT} WHERE id = ?",
            (str(plan_id),),
        ).fetchone()
        if row is None:
            raise NotFound(f"plan {plan_id}")
        return sql.row_to_plan(row)

    def _load_operation(
        self, conn: sqlite3.Connection, operation_id: UUID
    ) -> Operation:
        row = conn.execute(
            f"{_OPERATION_SELECT} WHERE id = ?",
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
            f"""
            {_OPERATION_SELECT}
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
            f"""
            {_MESSAGE_SELECT}
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
            f"""
            {_MESSAGE_SELECT}
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
