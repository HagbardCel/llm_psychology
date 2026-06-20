"""Unit tests for structured intake record persistence ordering."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from psychoanalyst_app.models.domain import Session, UserProfile, UserStatus
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    PresentingProblemRecord,
)
from psychoanalyst_app.orchestration.intake_record_persistence import (
    update_intake_record,
)
from psychoanalyst_app.orchestration.models import ConversationContext


def _profile() -> UserProfile:
    return UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _active_context() -> ConversationContext:
    return ConversationContext(
        session_id="session-123",
        user_profile=_profile(),
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
    )


def _record() -> IntakeRecord:
    return IntakeRecord(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="anxiety",
                evidence_quote="I feel anxious",
                source_role="user",
                source_message_index=1,
            )
        )
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_update_intake_record_missing_session_leaves_active_context_unchanged() -> None:
    context = _active_context()
    manager = MagicMock()
    manager.db_service = AsyncMock()
    manager.db_service.get_session.return_value = None
    manager.active_contexts = {"session-123": context}

    persisted = await update_intake_record(manager, "session-123", _record())

    assert persisted is False
    assert context.intake_record is None
    manager.db_service.save_session.assert_not_called()


@pytest.mark.trio
@pytest.mark.unit
async def test_update_intake_record_failed_save_leaves_active_context_unchanged() -> None:
    context = _active_context()
    session = Session(
        session_id="session-123",
        user_id="user-123",
        timestamp=datetime.now(),
        transcript=[],
    )
    manager = MagicMock()
    manager.db_service = AsyncMock()
    manager.db_service.get_session.return_value = session
    manager.db_service.save_session.return_value = False
    manager.active_contexts = {"session-123": context}

    persisted = await update_intake_record(manager, "session-123", _record())

    assert persisted is False
    assert context.intake_record is None
    assert context.intake_record_updated_at is None
    manager.db_service.save_session.assert_awaited_once_with(session)


@pytest.mark.trio
@pytest.mark.unit
async def test_update_intake_record_success_updates_db_and_active_context() -> None:
    context = _active_context()
    session = Session(
        session_id="session-123",
        user_id="user-123",
        timestamp=datetime.now(),
        transcript=[],
    )
    record = _record()
    manager = MagicMock()
    manager.db_service = AsyncMock()
    manager.db_service.get_session.return_value = session
    manager.db_service.save_session.return_value = True
    manager.active_contexts = {"session-123": context}

    persisted = await update_intake_record(manager, "session-123", record)

    assert persisted is True
    assert session.intake_record == record
    assert session.intake_record_updated_at is not None
    assert context.intake_record == record
    assert context.intake_record_updated_at == session.intake_record_updated_at
    manager.db_service.save_session.assert_awaited_once_with(session)
