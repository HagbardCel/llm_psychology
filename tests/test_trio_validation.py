"""
Simple Trio validation tests to verify the migration works.
"""

from datetime import datetime

import pytest
import trio


def test_trio_import():
    """Test that trio can be imported (sync test - no trio marker needed)."""
    assert trio is not None


@pytest.mark.trio
async def test_trio_sleep():
    """Test basic trio sleep functionality."""
    start = datetime.now()
    await trio.sleep(0.1)
    end = datetime.now()
    duration = (end - start).total_seconds()
    assert duration >= 0.1


@pytest.mark.trio
async def test_trio_nursery():
    """Test trio nursery structured concurrency."""
    results = []

    async def task(n):
        await trio.sleep(0.01)
        results.append(n)

    async with trio.open_nursery() as nursery:
        for i in range(5):
            nursery.start_soon(task, i)

    assert len(results) == 5
    assert set(results) == {0, 1, 2, 3, 4}


@pytest.mark.trio
async def test_trio_database_service(tmp_path):
    """Test pure Trio database service."""
    from models.data_models import UserProfile, UserStatus
    from services.migration_service import MigrationService
    from services.trio_db_service import TrioDatabaseService

    # Create service with temporary file database
    test_db_path = str(tmp_path / "test_validation.db")
    migration_service = MigrationService(test_db_path)
    db_service = TrioDatabaseService(test_db_path, migration_service)
    await db_service.initialize()

    # Test health check
    is_healthy = await db_service.health_check()
    assert is_healthy is True

    # Create and save user profile
    user_profile = UserProfile(
        user_id="test_user_validation",
        name="Validation User",
        birthdate=None,
        profession="Tester",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    success = await db_service.save_user_profile(user_profile)
    assert success is True

    # Retrieve user profile
    retrieved = await db_service.get_user_profile("test_user_validation")
    assert retrieved is not None
    assert retrieved.user_id == "test_user_validation"
    assert retrieved.name == "Validation User"


@pytest.mark.trio
async def test_trio_database_concurrent_operations(tmp_path):
    """Test concurrent database operations with nursery."""
    from models.data_models import UserProfile, UserStatus
    from services.migration_service import MigrationService
    from services.trio_db_service import TrioDatabaseService

    # Create service with temporary file database
    test_db_path = str(tmp_path / "test_concurrent.db")
    migration_service = MigrationService(test_db_path)
    db_service = TrioDatabaseService(test_db_path, migration_service)
    await db_service.initialize()

    results = []

    async def create_user(user_id):
        profile = UserProfile(
            user_id=user_id,
            name=f"User {user_id}",
            birthdate=None,
            profession="Test",
            status=UserStatus.PROFILE_ONLY,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        success = await db_service.save_user_profile(profile)
        results.append((user_id, success))

    # Run concurrent operations
    async with trio.open_nursery() as nursery:
        for i in range(10):
            nursery.start_soon(create_user, f"concurrent_user_{i}")

    # Verify all succeeded
    assert len(results) == 10
    assert all(success for _, success in results)

    # Verify all users exist
    for i in range(10):
        profile = await db_service.get_user_profile(f"concurrent_user_{i}")
        assert profile is not None
