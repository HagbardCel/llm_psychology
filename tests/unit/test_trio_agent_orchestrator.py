from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestration.models import AgentResponse, WorkflowState
from orchestration.trio_agent_orchestrator import TrioAgentOrchestrator


@pytest.fixture
def mock_dependencies():
    return {
        "service_container": MagicMock(),
        "workflow_engine": AsyncMock(),
        "conversation_manager": MagicMock(),
        "nursery": MagicMock(),
    }


@pytest.fixture
def orchestrator(mock_dependencies):
    return TrioAgentOrchestrator(
        mock_dependencies["service_container"],
        mock_dependencies["workflow_engine"],
        mock_dependencies["conversation_manager"],
        mock_dependencies["nursery"],
    )


@pytest.mark.trio
async def test_handle_agent_response_await_selection(orchestrator, mock_dependencies):
    """Test that await_selection action is handled correctly without errors."""
    response = AgentResponse(
        content="Test content",
        next_action="await_selection",
        next_state=None,
        metadata={"some": "metadata"},
    )

    # Execute the method
    await orchestrator._handle_agent_response("test_user", response)

    # Verify no transition was called
    mock_dependencies["workflow_engine"].transition.assert_not_called()


@pytest.mark.trio
async def test_handle_agent_response_transition(orchestrator, mock_dependencies):
    """Test that transition action triggers workflow state change."""
    response = AgentResponse(
        content="Test content",
        next_action="transition",
        next_state=WorkflowState.INTAKE_IN_PROGRESS,
        metadata={},
    )

    await orchestrator._handle_agent_response("test_user", response)

    mock_dependencies["workflow_engine"].transition.assert_called_once_with(
        "test_user", WorkflowState.INTAKE_IN_PROGRESS
    )


@pytest.mark.trio
async def test_handle_agent_response_continue(orchestrator, mock_dependencies):
    """Test that continue action does not trigger transition."""
    response = AgentResponse(
        content="Test content", next_action="continue", next_state=None, metadata={}
    )

    await orchestrator._handle_agent_response("test_user", response)

    mock_dependencies["workflow_engine"].transition.assert_not_called()


@pytest.mark.trio
async def test_handle_agent_response_complete(orchestrator, mock_dependencies):
    """Test that complete action is handled correctly."""
    response = AgentResponse(
        content="Test content",
        next_action="complete",
        next_state=None,
        metadata={"result": "success"},
    )

    await orchestrator._handle_agent_response("test_user", response)

    mock_dependencies["workflow_engine"].transition.assert_not_called()
