"""
Unit tests for TrioDatabaseService.

Tests database operations including session_briefing storage and retrieval.
"""

from datetime import datetime

import pytest
import trio

from psychoanalyst_app.models.data_models import Message, Session, TherapyPlan


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
        plan_details={
            "goals": ["Reduce anxiety", "Improve sleep"],
            "approaches": ["CBT", "Mindfulness"],
            "timeline": "12 weeks",
        },
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
    sample_therapy_plan.session_briefing = None
    success = await test_db_service.save_therapy_plan(sample_therapy_plan)
    assert success is True

    # Verify no briefing initially
    retrieved_plan = await test_db_service.get_therapy_plan(sample_therapy_plan.plan_id)
    assert retrieved_plan.session_briefing is None

    # Update the plan with a briefing
    sample_therapy_plan.session_briefing = sample_session_briefing
    sample_therapy_plan.updated_at = datetime.now()
    success = await test_db_service.save_therapy_plan(sample_therapy_plan)
    assert success is True

    # Retrieve the updated plan
    updated_plan = await test_db_service.get_therapy_plan(sample_therapy_plan.plan_id)

    # Verify briefing was added
    assert updated_plan.session_briefing is not None
    assert (
        updated_plan.session_briefing["session_summary"]
        == sample_session_briefing["session_summary"]
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_get_latest_therapy_plan_with_briefing(
    test_db_service, sample_session_briefing
):
    """
    Test that get_latest_therapy_plan correctly retrieves the plan with briefing.

    This is the method used by the server when generating resumption greetings.
    """
    user_id = "test_user_456"

    # Create and save first plan (no briefing)
    plan_v1 = TherapyPlan(
        plan_id="plan_v1",
        user_id=user_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        plan_details={"goals": ["Goal 1"]},
        initial_goals=["Goal 1"],
        current_progress="Baseline established",
        planned_interventions=["Supportive listening"],
        status="active",
        version=1,
        selected_therapy_style="CBT",
        session_briefing=None,
    )
    await test_db_service.save_therapy_plan(plan_v1)

    # Create and save second plan (with briefing)
    plan_v2 = TherapyPlan(
        plan_id="plan_v2",
        user_id=user_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        plan_details={"goals": ["Goal 1", "Goal 2"]},
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
    latest_plan = await test_db_service.get_latest_therapy_plan(user_id)

    # Verify we got the latest plan with briefing
    assert latest_plan is not None
    assert latest_plan.plan_id == "plan_v2"
    assert latest_plan.version == 2
    assert latest_plan.session_briefing is not None
    assert (
        latest_plan.session_briefing["session_summary"]
        == sample_session_briefing["session_summary"]
    )


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
                return (
                    "session_briefing" in plan_columns
                    and "plan_id" in session_columns
                    and "session_summary" in session_columns
                    and "session_briefing" in session_columns
                    and "plan_id" in profile_columns
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
