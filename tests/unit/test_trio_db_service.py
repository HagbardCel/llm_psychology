"""
Unit tests for TrioDatabaseService.

Tests database operations including session_briefing storage and retrieval.
"""

import json
from datetime import datetime

import pytest
import trio
from pydantic import ValidationError

from psychoanalyst_app.models.domain import (
    Message,
    Session,
    TherapyPlan,
    UserProfile,
)
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    PresentingProblemRecord,
)


@pytest.fixture
async def test_db_service(tmp_path):
    """Create a test database service with temporary database file."""
    from psychoanalyst_app.services.migration_service import MigrationService
    from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

    # Use temporary file for test database
    test_db_path = str(tmp_path / "test_db_service.db")

    migration_service = MigrationService(test_db_path)
    db = TrioDatabaseService(test_db_path, migration_service=migration_service)
    await db.initialize()

    yield db

    # Cleanup
    await db.clear_all_data()


@pytest.fixture
def sample_therapy_plan():
    """Create a sample therapy plan for testing."""
    return TherapyPlan(
        plan_id="test_plan_123",
        user_id="test_user_123",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        focus="Anxiety management",
        themes=["anxiety", "sleep"],
        timeline="12 weeks",
        initial_goals=["Reduce anxiety"],
        current_progress="Initial baseline established",
        planned_interventions=["CBT", "Mindfulness"],
        status="active",
        version=1,
        selected_therapy_style="CBT",
        session_briefing=None,
    )


@pytest.fixture
def sample_session_briefing():
    """Create a sample session briefing for testing."""
    return {
        "session_summary": "Patient discussed work-related stress and coping mechanisms",
        "key_themes": ["work stress", "coping strategies", "anxiety"],
        "emotional_state": "moderately anxious but engaged",
        "progress_notes": "Shows improved awareness of stress triggers",
        "next_session_focus": "Explore specific coping techniques for workplace anxiety",
        "generated_at": datetime.now().isoformat(),
    }


async def _save_profile(db, user_id: str) -> None:
    now = datetime.now()
    assert await db.save_user_profile(
        UserProfile(user_id=user_id, name="Test User", created_at=now, updated_at=now)
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_save_and_load_session_with_intake_record(test_db_service):
    user_id = "test_user_intake_record"
    await _save_profile(test_db_service, user_id)
    now = datetime.now()
    intake_record = IntakeRecord(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="work anxiety",
                evidence_quote="I feel anxious at work",
                source_message_index=0,
                source_role="user",
                confidence="high",
            )
        )
    )
    session = Session(
        session_id="intake-record-session",
        user_id=user_id,
        session_type="intake",
        timestamp=now,
        transcript=[],
        intake_record=intake_record,
        intake_record_updated_at=now,
    )

    assert await test_db_service.save_session(session)

    loaded = await test_db_service.get_session(session.session_id)

    assert loaded is not None
    assert loaded.intake_record == intake_record
    assert loaded.intake_record_updated_at == now




INVALID_PERSISTED_INTAKE_RECORD_JSON = json.dumps(
    {
        "presenting_problem": {
            "main_concern": {
                "source_message_index": -1,
            }
        }
    }
)


def _corrupt_persisted_intake_record(db, session_id: str, payload: str) -> None:
    import sqlite3

    conn = sqlite3.connect(db.db_path)
    try:
        conn.execute(
            "UPDATE sessions SET intake_record = ? WHERE session_id = ?",
            (payload, session_id),
        )
        conn.commit()
    finally:
        conn.close()


async def _save_intake_session(db, *, session_id: str, user_id: str) -> datetime:
    await _save_profile(db, user_id)
    now = datetime.now()
    intake_record = IntakeRecord(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="work anxiety",
                evidence_quote="I feel anxious at work",
                source_message_index=0,
                source_role="user",
                confidence="high",
            )
        )
    )
    session = Session(
        session_id=session_id,
        user_id=user_id,
        session_type="intake",
        timestamp=now,
        transcript=[],
        intake_record=intake_record,
        intake_record_updated_at=now,
    )
    assert await db.save_session(session)
    return now


@pytest.mark.trio
@pytest.mark.unit
@pytest.mark.parametrize(
    "corrupt_payload,expected_error",
    [
        ("{not json", json.JSONDecodeError),
        ("", json.JSONDecodeError),
        (INVALID_PERSISTED_INTAKE_RECORD_JSON, ValidationError),
    ],
)
async def test_invalid_persisted_intake_record_fails_loudly_on_get_session(
    test_db_service, corrupt_payload, expected_error
):
    session_id = "corrupt-intake-get-session"
    user_id = "corrupt_intake_get_user"
    await _save_intake_session(
        test_db_service, session_id=session_id, user_id=user_id
    )
    _corrupt_persisted_intake_record(test_db_service, session_id, corrupt_payload)

    with pytest.raises(expected_error):
        await test_db_service.get_session(session_id)


@pytest.mark.trio
@pytest.mark.unit
async def test_get_session_missing_id_preserves_soft_none_behavior(test_db_service):
    assert await test_db_service.get_session("missing-session-id") is None


@pytest.mark.trio
@pytest.mark.unit
@pytest.mark.parametrize(
    "list_read_method",
    [
        "get_user_sessions",
        "get_all_sessions_for_user",
        "get_recent_sessions",
    ],
)
async def test_invalid_persisted_intake_record_fails_loudly_on_list_reads(
    test_db_service, list_read_method
):
    session_id = f"corrupt-intake-{list_read_method}"
    user_id = f"corrupt_intake_{list_read_method}"
    await _save_intake_session(
        test_db_service, session_id=session_id, user_id=user_id
    )
    _corrupt_persisted_intake_record(
        test_db_service, session_id, INVALID_PERSISTED_INTAKE_RECORD_JSON
    )

    with pytest.raises(ValidationError):
        if list_read_method == "get_user_sessions":
            await test_db_service.get_user_sessions(user_id, limit=10)
        elif list_read_method == "get_all_sessions_for_user":
            await test_db_service.get_all_sessions_for_user(user_id)
        else:
            await test_db_service.get_recent_sessions(
                user_id, limit=10, enriched_only=False
            )


@pytest.mark.trio
@pytest.mark.unit
async def test_list_reads_missing_user_preserves_soft_empty_behavior(test_db_service):
    assert await test_db_service.get_user_sessions("missing-user", limit=10) == []
    assert await test_db_service.get_all_sessions_for_user("missing-user") == []
    assert (
        await test_db_service.get_recent_sessions(
            "missing-user", limit=10, enriched_only=False
        )
        == []
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_migration_adds_intake_record_columns_to_v1_sessions_table(tmp_path):
    """Existing v1 sessions tables gain nullable intake record columns on migrate."""
    import sqlite3

    from psychoanalyst_app.services.migration_service import MigrationService
    from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

    db_path = str(tmp_path / "v1_sessions_schema.db")
    now = datetime.now()
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)",
            (now.isoformat(),),
        )
        cursor.execute(
            """
            CREATE TABLE user_profiles (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                alias TEXT,
                date_of_birth TEXT,
                gender TEXT,
                cultural_background TEXT,
                primary_language TEXT NOT NULL DEFAULT 'English',
                profession TEXT,
                status TEXT NOT NULL,
                plan_id TEXT,
                parents TEXT,
                siblings TEXT,
                family_atmosphere TEXT,
                significant_events TEXT,
                education TEXT,
                work_history TEXT,
                relationship_to_work TEXT,
                relationships TEXT,
                social_context TEXT,
                current_situation TEXT,
                preferred_school TEXT,
                boundary_notes TEXT,
                frame_notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_type TEXT NOT NULL DEFAULT 'intake'
                    CHECK(session_type IN ('intake', 'therapy')),
                plan_id TEXT,
                timestamp TEXT NOT NULL,
                transcript TEXT NOT NULL,
                topics TEXT,
                session_summary TEXT,
                session_briefing TEXT,
                psychological_summary TEXT,
                dominant_affects TEXT,
                key_themes TEXT,
                notable_interactions TEXT,
                interpretations TEXT,
                patient_reactions TEXT,
                enriched INTEGER DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE therapy_plans (
                plan_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                focus TEXT NOT NULL,
                themes TEXT NOT NULL DEFAULT '[]',
                timeline TEXT,
                initial_goals TEXT,
                current_progress TEXT,
                planned_interventions TEXT,
                revision_recommendations TEXT NOT NULL DEFAULT '[]',
                status TEXT DEFAULT 'active',
                version INTEGER NOT NULL,
                selected_therapy_style TEXT,
                session_briefing TEXT,
                supersedes_plan_id TEXT,
                superseded_by_plan_id TEXT
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO user_profiles (
                user_id, name, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("legacy_user", "Legacy User", "PROFILE_ONLY", now.isoformat(), now.isoformat()),
        )
        cursor.execute(
            """
            INSERT INTO sessions (
                session_id, user_id, session_type, timestamp, transcript, enriched
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-session",
                "legacy_user",
                "intake",
                now.isoformat(),
                "[]",
                0,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    migration_service = MigrationService(db_path)
    await migration_service.run_migrations()

    conn = sqlite3.connect(db_path)
    try:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        version = conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0]
    finally:
        conn.close()

    assert version == 3
    assert "intake_record" in columns
    assert "intake_record_updated_at" in columns
    assert "intake_note_tracking_diagnostics" in columns

    db = TrioDatabaseService(db_path, migration_service=migration_service)
    await db.initialize()
    try:
        loaded = await db.get_session("legacy-session")
    finally:
        await db.clear_all_data()

    assert loaded is not None
    assert loaded.user_id == "legacy_user"
    assert loaded.session_type == "intake"
    assert loaded.intake_record is None
    assert loaded.intake_record_updated_at is None


@pytest.mark.trio
@pytest.mark.unit
async def test_save_and_load_therapy_plan_with_briefing(
    test_db_service, sample_therapy_plan, sample_session_briefing
):
    """
    Test that a therapy plan with session_briefing can be saved and retrieved correctly.

    This test verifies the critical bug fix for the missing session_briefing column.
    """
    # Add session briefing to the therapy plan
    await _save_profile(test_db_service, sample_therapy_plan.user_id)
    sample_therapy_plan.session_briefing = sample_session_briefing

    # Save the therapy plan with briefing
    success = await test_db_service.save_therapy_plan(sample_therapy_plan)
    assert success is True, "Failed to save therapy plan with session briefing"

    # Retrieve the therapy plan
    retrieved_plan = await test_db_service.get_therapy_plan(sample_therapy_plan.plan_id)

    # Verify the plan was retrieved
    assert retrieved_plan is not None, "Failed to retrieve therapy plan"
    assert retrieved_plan.plan_id == sample_therapy_plan.plan_id
    assert retrieved_plan.user_id == sample_therapy_plan.user_id
    assert retrieved_plan.focus == "Anxiety management"
    assert retrieved_plan.themes == ["anxiety", "sleep"]
    assert retrieved_plan.timeline == "12 weeks"
    assert retrieved_plan.initial_goals == ["Reduce anxiety"]
    assert retrieved_plan.current_progress.startswith("Initial baseline")
    assert retrieved_plan.planned_interventions[0] == "CBT"

    # Verify the session briefing was saved and retrieved correctly
    assert retrieved_plan.session_briefing is not None, "Session briefing was not saved"
    assert isinstance(
        retrieved_plan.session_briefing, dict
    ), "Session briefing should be a dict"

    # Verify briefing content
    assert (
        retrieved_plan.session_briefing["session_summary"]
        == sample_session_briefing["session_summary"]
    )
    assert (
        retrieved_plan.session_briefing["key_themes"]
        == sample_session_briefing["key_themes"]
    )
    assert (
        retrieved_plan.session_briefing["emotional_state"]
        == sample_session_briefing["emotional_state"]
    )
    assert "generated_at" in retrieved_plan.session_briefing


@pytest.mark.trio
@pytest.mark.unit
async def test_save_therapy_plan_without_briefing(test_db_service, sample_therapy_plan):
    """
    Test that a therapy plan without session_briefing can still be saved.

    This ensures backward compatibility with plans that don't have briefings yet.
    """
    # Ensure session_briefing is None
    await _save_profile(test_db_service, sample_therapy_plan.user_id)
    sample_therapy_plan.session_briefing = None

    # Save the therapy plan
    success = await test_db_service.save_therapy_plan(sample_therapy_plan)
    assert success is True, "Failed to save therapy plan without session briefing"

    # Retrieve the therapy plan
    retrieved_plan = await test_db_service.get_therapy_plan(sample_therapy_plan.plan_id)

    # Verify the plan was retrieved
    assert retrieved_plan is not None
    assert retrieved_plan.plan_id == sample_therapy_plan.plan_id

    # Verify session_briefing is None
    assert retrieved_plan.session_briefing is None


@pytest.mark.trio
@pytest.mark.unit
async def test_update_therapy_plan_with_briefing(
    test_db_service, sample_therapy_plan, sample_session_briefing
):
    """
    Test that a therapy plan can be updated to add a session briefing.

    This simulates the reflection agent adding a briefing after a session.
    """
    # First save plan without briefing
    await _save_profile(test_db_service, sample_therapy_plan.user_id)
    sample_therapy_plan.session_briefing = None
    success = await test_db_service.save_therapy_plan(sample_therapy_plan)
    assert success is True

    # Verify no briefing initially
    retrieved_plan = await test_db_service.get_therapy_plan(sample_therapy_plan.plan_id)
    assert retrieved_plan.session_briefing is None

    # Update the plan with a briefing
    revised_plan = sample_therapy_plan.model_copy(
        update={
            "plan_id": "test_plan_124",
            "session_briefing": sample_session_briefing,
            "updated_at": datetime.now(),
        }
    )
    success = await test_db_service.save_therapy_plan(revised_plan)
    assert success is True

    # Retrieve the updated plan
    updated_plan = await test_db_service.get_therapy_plan(revised_plan.plan_id)

    # Verify briefing was added
    assert updated_plan.session_briefing is not None
    assert (
        updated_plan.session_briefing["session_summary"]
        == sample_session_briefing["session_summary"]
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_get_current_therapy_plan_with_briefing(
    test_db_service, sample_session_briefing
):
    """
    Test that get_current_therapy_plan correctly retrieves the plan with briefing.

    This is the method used by the server when generating resumption greetings.
    """
    user_id = "test_user_456"
    await _save_profile(test_db_service, user_id)

    # Create and save first plan (no briefing)
    plan_v1 = TherapyPlan(
        plan_id="plan_v1",
        user_id=user_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        focus="Goal 1",
        initial_goals=["Goal 1"],
        current_progress="Baseline established",
        planned_interventions=["Supportive listening"],
        status="active",
        version=1,
        selected_therapy_style="CBT",
        session_briefing=None,
    )
    await test_db_service.save_therapy_plan(plan_v1)
    historical_session = Session(
        session_id="therapy-session-v1",
        user_id=user_id,
        session_type="therapy",
        plan_id=plan_v1.plan_id,
        timestamp=datetime.now(),
        transcript=[],
    )
    assert await test_db_service.save_session(historical_session)

    # Create and save second plan (with briefing)
    plan_v2 = TherapyPlan(
        plan_id="plan_v2",
        user_id=user_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        focus="Goal 1 and Goal 2",
        initial_goals=["Goal 1", "Goal 2"],
        current_progress="Progress improving",
        planned_interventions=["CBT"],
        status="active",
        version=2,
        selected_therapy_style="CBT",
        session_briefing=sample_session_briefing,
    )
    await test_db_service.save_therapy_plan(plan_v2)

    # Get latest plan
    latest_plan = await test_db_service.get_current_therapy_plan(user_id)

    # Verify we got the latest plan with briefing
    assert latest_plan is not None
    assert latest_plan.plan_id == "plan_v2"
    assert latest_plan.version == 2
    assert latest_plan.session_briefing is not None
    assert (
        latest_plan.session_briefing["session_summary"]
        == sample_session_briefing["session_summary"]
    )
    previous_plan = await test_db_service.get_therapy_plan("plan_v1")
    profile = await test_db_service.get_user_profile(user_id)
    persisted_session = await test_db_service.get_session(historical_session.session_id)
    assert previous_plan.status == "superseded"
    assert previous_plan.superseded_by_plan_id == "plan_v2"
    assert latest_plan.supersedes_plan_id == "plan_v1"
    assert profile.plan_id == "plan_v2"
    assert persisted_session.plan_id == "plan_v1"


@pytest.mark.trio
@pytest.mark.unit
async def test_database_migration_adds_session_briefing_column(test_db_service):
    """
    Test that the database migration includes current schema columns.

    This test verifies that the baseline schema definition is correct.
    """
    # The database is already initialized by the fixture
    # Verify we can query the column information

    async def check_column_exists():
        """Check if expected columns exist using trio.to_thread."""

        def _check():
            conn = test_db_service._create_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(therapy_plans)")
                plan_columns = {col[1] for col in cursor.fetchall()}
                cursor.execute("PRAGMA table_info(sessions)")
                session_columns = {col[1] for col in cursor.fetchall()}
                cursor.execute("PRAGMA table_info(user_profiles)")
                profile_columns = {col[1] for col in cursor.fetchall()}
                cursor.execute("PRAGMA table_info(assessment_recommendations)")
                recommendation_columns = {col[1] for col in cursor.fetchall()}
                plan_indexes = {
                    row[1] for row in cursor.execute("PRAGMA index_list(therapy_plans)")
                }
                return (
                    {
                        "session_briefing",
                        "supersedes_plan_id",
                        "superseded_by_plan_id",
                        "revision_recommendations",
                    }.issubset(plan_columns)
                    and "idx_therapy_plans_current_user" in plan_indexes
                    and "plan_id" in session_columns
                    and "session_summary" in session_columns
                    and "session_briefing" in session_columns
                    and "plan_id" in profile_columns
                    and {
                        "user_id",
                        "intake_session_block_id",
                        "recommendations",
                        "created_at",
                    }.issubset(recommendation_columns)
                )
            finally:
                conn.close()

        return await trio.to_thread.run_sync(_check)

    has_column = await check_column_exists()
    assert (
        has_column is True
    ), "Expected session/user profile columns should exist in the schema"


@pytest.mark.trio
@pytest.mark.unit
async def test_plan_revision_rolls_back_when_profile_history_write_fails(
    test_db_service, sample_therapy_plan
):
    """A failed revision write must leave the previous row current."""
    await _save_profile(test_db_service, sample_therapy_plan.user_id)
    assert await test_db_service.save_therapy_plan(sample_therapy_plan)
    conn = test_db_service._create_connection()
    try:
        conn.execute(
            """
            CREATE TRIGGER reject_plan_history
            BEFORE INSERT ON user_profile_history
            WHEN NEW.change_summary LIKE 'Linked therapy plan revision%'
            BEGIN
                SELECT RAISE(ABORT, 'reject history');
            END
            """
        )
        conn.commit()
    finally:
        conn.close()

    revised = sample_therapy_plan.model_copy(update={"plan_id": "test_plan_rollback"})
    assert not await test_db_service.save_therapy_plan(revised)
    current = await test_db_service.get_current_therapy_plan(sample_therapy_plan.user_id)
    assert current.plan_id == sample_therapy_plan.plan_id
    assert current.status == "active"
    assert current.superseded_by_plan_id is None


@pytest.mark.trio
@pytest.mark.unit
async def test_migration_rejects_legacy_schema_with_recreation_instruction(tmp_path):
    """Legacy DBs fail closed because foundation rows are intentionally incompatible."""
    import sqlite3

    from psychoanalyst_app.services.migration_service import MigrationService
    from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

    db_path = str(tmp_path / "legacy_profile_schema.db")
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (9, ?)",
            (datetime.now().isoformat(),),
        )
        cursor.execute(
            """
            CREATE TABLE user_profiles (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                birthdate TEXT,
                profession TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                alias TEXT,
                date_of_birth TEXT,
                gender TEXT,
                cultural_background TEXT,
                primary_language TEXT NOT NULL DEFAULT 'English',
                parents TEXT,
                siblings TEXT,
                family_atmosphere TEXT,
                significant_events TEXT,
                education TEXT,
                work_history TEXT,
                relationship_to_work TEXT,
                relationships TEXT,
                social_context TEXT,
                current_situation TEXT,
                preferred_school TEXT,
                session_mode TEXT NOT NULL DEFAULT 'virtual',
                boundary_notes TEXT,
                frame_notes TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                plan_id TEXT,
                timestamp TEXT NOT NULL,
                transcript TEXT NOT NULL,
                topics TEXT,
                session_summary TEXT,
                session_briefing TEXT,
                psychological_summary TEXT,
                dominant_affects TEXT,
                key_themes TEXT,
                notable_interactions TEXT,
                interpretations TEXT,
                patient_reactions TEXT,
                enriched INTEGER DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE therapy_plans (
                plan_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                focus TEXT NOT NULL,
                themes TEXT NOT NULL DEFAULT '[]',
                timeline TEXT,
                initial_goals TEXT,
                current_progress TEXT,
                planned_interventions TEXT,
                status TEXT DEFAULT 'active',
                version INTEGER NOT NULL,
                selected_therapy_style TEXT,
                session_briefing TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE patient_analysis (
                analysis_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                analysis_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by_session TEXT,
                change_summary TEXT,
                superseded_by TEXT,
                UNIQUE(user_id, version)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE session_enrichment_jobs (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE user_profile_history (
                history_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                previous_profile_data TEXT NOT NULL,
                new_profile_data TEXT NOT NULL,
                change_summary TEXT,
                created_at TEXT NOT NULL,
                created_by_session TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    migration_service = MigrationService(db_path)
    db = TrioDatabaseService(db_path, migration_service=migration_service)
    with pytest.raises(
        RuntimeError,
        match="delete the SQLite database",
    ):
        await db.initialize()


@pytest.mark.trio
@pytest.mark.unit
async def test_migration_connection_configures_file_backed_sqlite(tmp_path):
    """Migration connections should apply local SQLite resilience pragmas."""
    from psychoanalyst_app.services.migration_service import MigrationService

    migration_service = MigrationService(
        str(tmp_path / "migration_pragmas.db"),
        busy_timeout_seconds=9,
    )

    def _check_pragmas():
        conn = migration_service._get_connection()
        try:
            return {
                "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
                "synchronous": conn.execute("PRAGMA synchronous").fetchone()[0],
                "busy_timeout": conn.execute("PRAGMA busy_timeout").fetchone()[0],
            }
        finally:
            conn.close()

    pragmas = await trio.to_thread.run_sync(_check_pragmas)

    assert pragmas["journal_mode"] == "wal"
    assert pragmas["synchronous"] == 1
    assert pragmas["busy_timeout"] == 9000


@pytest.mark.trio
@pytest.mark.unit
async def test_update_session_reflection_persists_summary_and_briefing(
    test_db_service,
):
    """Ensure session summary and briefing persist to the session row."""
    session = Session(
        session_id="session_reflection_1",
        user_id="user_reflection_1",
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="assistant",
                content="Session content",
                timestamp=datetime.now(),
            )
        ],
        topics=[],
    )
    assert await test_db_service.save_session(session)

    briefing = {"briefing_type": "resumption", "generated_at": datetime.now().isoformat()}
    summary = "Reflection summary text."
    success = await test_db_service.update_session_reflection(
        session.session_id,
        summary,
        briefing,
    )
    assert success is True

    stored = await test_db_service.get_session(session.session_id)
    assert stored is not None
    assert stored.session_summary == summary
    assert stored.session_briefing == briefing


@pytest.mark.trio
@pytest.mark.unit
async def test_assessment_recommendations_round_trip(test_db_service):
    """Assessment recommendations persist for reconnect/restart recovery."""
    profile = UserProfile(
        user_id="assessment_user_1",
        name="Assessment User",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    assert await test_db_service.save_user_profile(profile)

    recommendations = [
        {
            "style_id": "cbt",
            "explanation": "Structured practical support.",
            "score": 0.92,
        }
    ]
    saved = await test_db_service.save_assessment_recommendations(
        user_id=profile.user_id,
        intake_session_block_id="intake_session_1",
        recommendations=recommendations,
    )
    assert saved is True

    loaded = await test_db_service.get_latest_assessment_recommendations(
        profile.user_id
    )
    assert loaded == recommendations


@pytest.mark.trio
@pytest.mark.unit
async def test_profile_update_preserves_assessment_recommendations(test_db_service):
    """Profile UPSERT must not cascade-delete durable assessment handoff rows."""
    profile = UserProfile(
        user_id="recommendation_upsert_user",
        name="Before Update",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    assert await test_db_service.save_user_profile(profile)
    recommendations = [{"style_id": "cbt", "score": 0.9, "explanation": "Structured"}]
    assert await test_db_service.save_assessment_recommendations(
        user_id=profile.user_id,
        intake_session_block_id="intake_1",
        recommendations=recommendations,
    )

    profile.name = "After Update"
    profile.updated_at = datetime.now()
    assert await test_db_service.update_user_profile(profile)

    loaded = await test_db_service.get_latest_assessment_recommendations(profile.user_id)
    assert loaded == recommendations
