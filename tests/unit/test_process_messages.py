from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from psychoanalyst_app.models.domain import Session, UserProfile
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    PresentingProblemRecord,
)
from psychoanalyst_app.models.llm_outputs import StructuredUserProfileOutput
from psychoanalyst_app.orchestration.models import AgentResponse, WorkflowState
from psychoanalyst_app.orchestration.process_messages import finalize_agent_response


@pytest.mark.trio
async def test_finalize_agent_response_forwards_incomplete_profile():
    trio_db_service = AsyncMock()
    trio_db_service.get_user_profile.return_value = UserProfile(
        user_id="guest_user",
        name="Guest",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    trio_db_service.update_user_profile.return_value = True

    service_container = MagicMock()
    service_container.get.return_value = trio_db_service
    response_handler = AsyncMock()

    agent_response = AgentResponse(
        content="Hi",
        next_action="transition",
        next_state=WorkflowState.INTAKE_IN_PROGRESS,
        metadata={"user_profile": StructuredUserProfileOutput(name="Guest")},
    )

    await finalize_agent_response(
        service_container,
        response_handler,
        "guest_user",
        "session_123",
        agent_response,
    )

    assert agent_response.next_state == WorkflowState.INTAKE_IN_PROGRESS
    assert agent_response.next_action == "transition"
    response_handler.handle.assert_called_once_with(
        "guest_user",
        "session_123",
        agent_response,
    )


@pytest.mark.trio
async def test_finalize_agent_response_persists_intake_record_metadata():
    record_payload = IntakeRecord(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="anxiety",
                evidence_quote="I feel anxious",
                source_message_index=1,
                source_role="user",
            )
        )
    ).model_dump(mode="json")
    session = Session(
        session_id="session_123",
        user_id="user_123",
        timestamp=datetime.now(),
        transcript=[],
    )
    trio_db_service = AsyncMock()
    trio_db_service.get_session.return_value = session
    trio_db_service.save_session.return_value = True

    service_container = MagicMock()
    service_container.get.return_value = trio_db_service
    conversation_manager = MagicMock()
    conversation_manager.active_contexts = {}
    conversation_manager.db_service = trio_db_service
    response_handler = AsyncMock()
    response_handler.conversation_manager = conversation_manager

    agent_response = AgentResponse(
        content="Hi",
        next_action="continue",
        metadata={"intake_record": record_payload},
    )

    await finalize_agent_response(
        service_container,
        response_handler,
        "user_123",
        "session_123",
        agent_response,
    )

    assert isinstance(session.intake_record, IntakeRecord)
    assert session.intake_record.presenting_problem.main_concern.value == "anxiety"
    assert session.intake_record_updated_at is not None
    trio_db_service.save_session.assert_awaited_once_with(session)
    response_handler.handle.assert_called_once_with(
        "user_123",
        "session_123",
        agent_response,
    )


@pytest.mark.trio
async def test_finalize_agent_response_skips_unchanged_intake_record_metadata():
    record_payload = IntakeRecord().model_dump(mode="json")
    trio_db_service = AsyncMock()

    service_container = MagicMock()
    service_container.get.return_value = trio_db_service
    response_handler = AsyncMock()

    agent_response = AgentResponse(
        content="Hi",
        next_action="continue",
        metadata={
            "intake_record": record_payload,
            "intake_record_persistence": {
                "should_persist": False,
                "record_changed": False,
            },
        },
    )

    await finalize_agent_response(
        service_container,
        response_handler,
        "user_123",
        "session_123",
        agent_response,
    )

    trio_db_service.get_session.assert_not_called()
    trio_db_service.save_session.assert_not_called()
    response_handler.handle.assert_called_once_with(
        "user_123",
        "session_123",
        agent_response,
    )


@pytest.mark.trio
async def test_finalize_agent_response_ignores_unexpected_intake_record_type():
    trio_db_service = AsyncMock()
    service_container = MagicMock()
    service_container.get.return_value = trio_db_service
    response_handler = AsyncMock()

    agent_response = AgentResponse(
        content="Hi",
        next_action="continue",
        metadata={"intake_record": "not a record"},
    )

    await finalize_agent_response(
        service_container,
        response_handler,
        "user_123",
        "session_123",
        agent_response,
    )

    trio_db_service.get_session.assert_not_called()
    trio_db_service.save_session.assert_not_called()
    response_handler.handle.assert_called_once_with(
        "user_123",
        "session_123",
        agent_response,
    )
