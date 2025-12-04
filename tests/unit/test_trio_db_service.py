"""
Unit tests for TrioDatabaseService.

Tests database operations including session_briefing storage and retrieval.
"""

from datetime import datetime

import pytest
import trio

from models.data_models import TherapyPlan


@pytest.fixture
async def test_db_service(tmp_path):
    """Create a test database service with temporary database file."""
    from services.migration_service import MigrationService
    from services.trio_db_service import TrioDatabaseService

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

    # Verify the session briefing was saved and retrieved correctly
    assert retrieved_plan.session_briefing is not None, "Session briefing was not saved"
    assert isinstance(retrieved_plan.session_briefing, dict), (
        "Session briefing should be a dict"
    )

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
    Test that the database migration properly adds the session_briefing column.

    This test verifies that the migration logic in _sync_initialize works correctly.
    Note: In practice, with :memory: databases, the table is always created fresh,
    so this test primarily validates the schema definition is correct.
    """
    # The database is already initialized by the fixture
    # Verify we can query the column information

    async def check_column_exists():
        """Check if session_briefing column exists using trio.to_thread."""

        def _check():
            conn = test_db_service._create_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(therapy_plans)")
                columns = {col[1] for col in cursor.fetchall()}
                return "session_briefing" in columns
            finally:
                conn.close()

        return await trio.to_thread.run_sync(_check)

    has_column = await check_column_exists()
    assert has_column is True, (
        "session_briefing column should exist in therapy_plans table"
    )


# Authentication Tests


@pytest.fixture
def sample_user_credentials():
    """Create sample user credentials for testing."""
    from models.auth_models import UserCredentials

    return UserCredentials(
        user_id="test_user_auth_123",
        username="testuser",
        password_hash="$2b$12$hashedpassword123",
        created_at=datetime.now(),
        last_login=None,
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_create_user_credentials(test_db_service, sample_user_credentials):
    """Test creating user credentials in database."""
    success = await test_db_service.create_user_credentials(sample_user_credentials)
    assert success is True, "Failed to create user credentials"

    # Verify credentials can be retrieved
    retrieved = await test_db_service.get_user_credentials(
        sample_user_credentials.username
    )
    assert retrieved is not None
    assert retrieved.user_id == sample_user_credentials.user_id
    assert retrieved.username == sample_user_credentials.username
    assert retrieved.password_hash == sample_user_credentials.password_hash


@pytest.mark.trio
@pytest.mark.unit
async def test_create_duplicate_username(test_db_service, sample_user_credentials):
    """Test that duplicate usernames are rejected."""
    # Create first user
    success = await test_db_service.create_user_credentials(sample_user_credentials)
    assert success is True

    # Try to create second user with same username
    from models.auth_models import UserCredentials

    duplicate = UserCredentials(
        user_id="different_user_id",
        username=sample_user_credentials.username,  # Same username
        password_hash="different_hash",
        created_at=datetime.now(),
        last_login=None,
    )

    success = await test_db_service.create_user_credentials(duplicate)
    assert success is False, "Should reject duplicate username"


@pytest.mark.trio
@pytest.mark.unit
async def test_get_user_credentials_not_found(test_db_service):
    """Test retrieving non-existent user credentials."""
    retrieved = await test_db_service.get_user_credentials("nonexistent_user")
    assert retrieved is None


@pytest.mark.trio
@pytest.mark.unit
async def test_update_last_login(test_db_service, sample_user_credentials):
    """Test updating last login time."""
    # Create user
    success = await test_db_service.create_user_credentials(sample_user_credentials)
    assert success is True

    # Update last login
    login_time = datetime.now()
    success = await test_db_service.update_last_login(
        sample_user_credentials.user_id, login_time
    )
    assert success is True

    # Verify last login was updated
    retrieved = await test_db_service.get_user_credentials(
        sample_user_credentials.username
    )
    assert retrieved is not None
    assert retrieved.last_login is not None
    # Check within 1 second tolerance
    time_diff = abs((retrieved.last_login - login_time).total_seconds())
    assert time_diff < 1.0


@pytest.mark.trio
@pytest.mark.unit
async def test_get_user_by_username(test_db_service, sample_user_credentials):
    """Test getting user profile by username."""
    from models.data_models import UserProfile, UserStatus

    # Create user credentials
    success = await test_db_service.create_user_credentials(sample_user_credentials)
    assert success is True

    # Create user profile
    profile = UserProfile(
        user_id=sample_user_credentials.user_id,
        name="Test User",
        birthdate=None,
        profession=None,
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    success = await test_db_service.save_user_profile(profile)
    assert success is True

    # Get user by username
    retrieved_profile = await test_db_service.get_user_by_username(
        sample_user_credentials.username
    )
    assert retrieved_profile is not None
    assert retrieved_profile.user_id == sample_user_credentials.user_id
    assert retrieved_profile.name == "Test User"


@pytest.mark.trio
@pytest.mark.unit
async def test_get_user_by_username_no_profile(test_db_service, sample_user_credentials):
    """Test getting user by username when profile doesn't exist."""
    # Create credentials but no profile
    success = await test_db_service.create_user_credentials(sample_user_credentials)
    assert success is True

    # Try to get profile by username
    retrieved_profile = await test_db_service.get_user_by_username(
        sample_user_credentials.username
    )
    assert retrieved_profile is None


@pytest.mark.trio
@pytest.mark.unit
async def test_auth_tables_migration(test_db_service):
    """Test that authentication tables are created by migration."""

    async def check_auth_tables_exist():
        """Check if user_credentials table exists."""

        def _check():
            conn = test_db_service._create_connection()
            try:
                cursor = conn.cursor()
                # Check for user_credentials table
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='user_credentials'"
                )
                table_exists = cursor.fetchone() is not None

                # Check for username index
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_user_credentials_username'"
                )
                index_exists = cursor.fetchone() is not None

                return table_exists and index_exists
            finally:
                conn.close()

        return await trio.to_thread.run_sync(_check)

    tables_exist = await check_auth_tables_exist()
    assert tables_exist is True, "user_credentials table and index should exist"
