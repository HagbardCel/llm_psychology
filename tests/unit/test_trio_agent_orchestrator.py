from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.data_models import UserProfile, UserStatus
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


@pytest.mark.trio
async def test_create_therapy_plan_success(orchestrator, mock_dependencies):
    """Test successful therapy plan creation via orchestrator."""
    # Setup mocks
    mock_db_service = AsyncMock()
    mock_style_service = MagicMock()

    # Mock service container
    def get_service(name):
        if name == "trio_db_service":
            return mock_db_service
        elif name == "style_service":
            return mock_style_service
        return MagicMock()

    orchestrator.service_container.get = get_service

    # Mock style service
    mock_style_service.get_available_styles.return_value = ["freud", "jung", "cbt"]

    # Create and mock user profile
    profile = UserProfile(
        user_id="test_user",
        name="Test",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    mock_db_service.get_user_profile.return_value = profile
    mock_db_service.get_latest_therapy_plan.return_value = None
    mock_db_service.save_therapy_plan.return_value = True
    mock_db_service.save_user_profile.return_value = True

    # Create therapy plan
    plan = await orchestrator.create_therapy_plan("test_user", "freud")

    # Assertions
    assert plan.user_id == "test_user"
    assert plan.version == 1
    assert plan.selected_therapy_style == "freud"
    assert mock_db_service.save_therapy_plan.called
    assert mock_db_service.save_user_profile.called


@pytest.mark.trio
async def test_create_therapy_plan_invalid_style(orchestrator, mock_dependencies):
    """Test therapy plan creation with invalid style."""
    # Setup mocks
    mock_style_service = MagicMock()

    def get_service(name):
        if name == "style_service":
            return mock_style_service
        return MagicMock()

    orchestrator.service_container.get = get_service
    mock_style_service.get_available_styles.return_value = ["freud", "jung", "cbt"]

    # Attempt to create plan with invalid style
    with pytest.raises(ValueError, match="Invalid therapy style"):
        await orchestrator.create_therapy_plan("test_user", "invalid_style")


@pytest.mark.trio
async def test_create_therapy_plan_prevents_duplicate_v1(
    orchestrator, mock_dependencies
):
    """Test that creating plan twice returns existing version 1."""
    # Setup mocks
    mock_db_service = AsyncMock()
    mock_style_service = MagicMock()

    def get_service(name):
        if name == "trio_db_service":
            return mock_db_service
        elif name == "style_service":
            return mock_style_service
        return MagicMock()

    orchestrator.service_container.get = get_service
    mock_style_service.get_available_styles.return_value = ["freud", "jung", "cbt"]

    # Create profile
    profile = UserProfile(
        user_id="test_user",
        name="Test",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    mock_db_service.get_user_profile.return_value = profile

    # Mock existing plan
    from models.data_models import TherapyPlan
    existing_plan = TherapyPlan(
        plan_id="existing_plan_id",
        user_id="test_user",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        plan_details={},
        version=1,
        selected_therapy_style="freud"
    )
    mock_db_service.get_latest_therapy_plan.return_value = existing_plan

    # Try to create plan - should return existing
    plan = await orchestrator.create_therapy_plan("test_user", "freud")

    # Should return same plan without saving
    assert plan.plan_id == "existing_plan_id"
    assert plan.version == 1
    mock_db_service.save_therapy_plan.assert_not_called()
