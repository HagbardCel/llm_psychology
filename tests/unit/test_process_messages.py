from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from psychoanalyst_app.models.data_models import UserProfile
from psychoanalyst_app.models.structured_output_models import StructuredUserProfileOutput
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
