"""
Unit tests for session timer functionality.

Tests the time tracking and extension features of therapy sessions.
"""

from datetime import datetime, timedelta

import pytest

from psychoanalyst_app.models.domain import Message, TherapyPlan, UserProfile, UserStatus
from psychoanalyst_app.orchestration.models import ConversationContext


def test_time_elapsed_calculation():
    """Test that time_elapsed_minutes calculates correctly."""
    # Create a context with a start time 10 minutes ago
    start_time = datetime.now() - timedelta(minutes=10)
    context = ConversationContext(
        session_id="test-session",
        user_profile=UserProfile(
            user_id="test-user",
            name="Test User",
            status=UserStatus.THERAPY_IN_PROGRESS,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=start_time,
        duration_minutes=45,
    )

    # Should be approximately 10 minutes (allow for small timing variance)
    assert 9.5 <= context.time_elapsed_minutes <= 10.5


def test_time_remaining_calculation():
    """Test that time_remaining_minutes calculates correctly."""
    # Create a context with a start time 10 minutes ago
    start_time = datetime.now() - timedelta(minutes=10)
    context = ConversationContext(
        session_id="test-session",
        user_profile=UserProfile(
            user_id="test-user",
            name="Test User",
            status=UserStatus.THERAPY_IN_PROGRESS,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=start_time,
        duration_minutes=45,
    )

    # Should be approximately 35 minutes remaining
    assert 34.5 <= context.time_remaining_minutes <= 35.5


def test_is_time_up():
    """Test that is_time_up returns True when time has expired."""
    # Create a context with a start time 50 minutes ago (past the 45 min duration)
    start_time = datetime.now() - timedelta(minutes=50)
    context = ConversationContext(
        session_id="test-session",
        user_profile=UserProfile(
            user_id="test-user",
            name="Test User",
            status=UserStatus.THERAPY_IN_PROGRESS,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=start_time,
        duration_minutes=45,
    )

    assert context.is_time_up is True


def test_is_time_not_up():
    """Test that is_time_up returns False when time has not expired."""
    # Create a context with a start time 10 minutes ago
    start_time = datetime.now() - timedelta(minutes=10)
    context = ConversationContext(
        session_id="test-session",
        user_profile=UserProfile(
            user_id="test-user",
            name="Test User",
            status=UserStatus.THERAPY_IN_PROGRESS,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=start_time,
        duration_minutes=45,
    )

    assert context.is_time_up is False


def test_can_extend():
    """Test that can_extend works correctly."""
    context = ConversationContext(
        session_id="test-session",
        user_profile=UserProfile(
            user_id="test-user",
            name="Test User",
            status=UserStatus.THERAPY_IN_PROGRESS,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=45,
        extensions_used=0,
        max_extensions=2,
    )

    # Should be able to extend (0 extensions used, max is 2)
    assert context.can_extend is True

    # Use 2 extensions
    context.extensions_used = 2

    # Should not be able to extend anymore
    assert context.can_extend is False


def test_extension_adds_time():
    """Test that extensions add 5 minutes each to the total duration."""
    # Start time 40 minutes ago
    start_time = datetime.now() - timedelta(minutes=40)
    context = ConversationContext(
        session_id="test-session",
        user_profile=UserProfile(
            user_id="test-user",
            name="Test User",
            status=UserStatus.THERAPY_IN_PROGRESS,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=start_time,
        duration_minutes=45,
        extensions_used=0,
        max_extensions=2,
    )

    # Without extension: 45 - 40 = 5 minutes remaining
    assert 4.5 <= context.time_remaining_minutes <= 5.5

    # With 1 extension: (45 + 5) - 40 = 10 minutes remaining
    context.extensions_used = 1
    assert 9.5 <= context.time_remaining_minutes <= 10.5

    # With 2 extensions: (45 + 10) - 40 = 15 minutes remaining
    context.extensions_used = 2
    assert 14.5 <= context.time_remaining_minutes <= 15.5


def test_time_up_with_extensions():
    """Test that is_time_up accounts for extensions."""
    # Start time 50 minutes ago (past base duration but within extended time)
    start_time = datetime.now() - timedelta(minutes=50)
    context = ConversationContext(
        session_id="test-session",
        user_profile=UserProfile(
            user_id="test-user",
            name="Test User",
            status=UserStatus.THERAPY_IN_PROGRESS,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=start_time,
        duration_minutes=45,
        extensions_used=1,  # 1 extension = +5 minutes
        max_extensions=2,
    )

    # 45 + 5 = 50 minutes total, 50 minutes elapsed, so time is just up
    # Allow small variance
    assert context.time_remaining_minutes <= 0.5

    # With 2 extensions, time should not be up yet
    context.extensions_used = 2  # 2 extensions = +10 minutes
    # 45 + 10 = 55 minutes total, 50 minutes elapsed, 5 minutes remaining
    assert 4.5 <= context.time_remaining_minutes <= 5.5
    assert context.is_time_up is False
