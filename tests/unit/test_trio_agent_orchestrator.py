from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from psychoanalyst_app.models.data_models import TherapyPlan, UserProfile, UserStatus
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    WorkflowEvent,
    WorkflowState,
)
from psychoanalyst_app.orchestration.trio_agent_orchestrator import TrioAgentOrchestrator


@pytest.fixture
def mock_dependencies():
    workflow_engine = MagicMock()
    workflow_engine.get_user_state = AsyncMock(return_value=WorkflowState.NEW)
    workflow_engine.transition = AsyncMock()
    workflow_engine.get_user_state.return_value = WorkflowState.NEW
    return {
        "service_container": MagicMock(),
        "workflow_engine": workflow_engine,
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

    # Execute the method (method signature requires user_id, session_id, agent_response)
    await orchestrator.response_handler.handle("test_user", "test_session", response)

    # Verify no transition was called
    mock_dependencies["workflow_engine"].transition.assert_not_called()


@pytest.mark.trio
async def test_handle_agent_response_transition(orchestrator, mock_dependencies):
    """Test that transition action triggers workflow state change."""
    response = AgentResponse(
        content="Test content",
        next_action="transition",
        next_state=None,
        workflow_event=WorkflowEvent.COMPLETE_ASSESSMENT,
        metadata={},
    )
    mock_dependencies["workflow_engine"].get_user_state.return_value = (
        WorkflowState.ASSESSMENT_IN_PROGRESS
    )
    mock_dependencies["workflow_engine"].get_next_state = MagicMock(
        return_value=WorkflowState.ASSESSMENT_COMPLETE
    )

    await orchestrator.response_handler.handle("test_user", "test_session", response)

    mock_dependencies["workflow_engine"].transition.assert_called_once_with(
        "test_user",
        WorkflowState.ASSESSMENT_COMPLETE,
        event=WorkflowEvent.COMPLETE_ASSESSMENT,
    )


@pytest.mark.trio
async def test_handle_agent_response_continue(orchestrator, mock_dependencies):
    """Test that continue action does not trigger transition."""
    response = AgentResponse(
        content="Test content", next_action="continue", next_state=None, metadata={}
    )

    await orchestrator.response_handler.handle("test_user", "test_session", response)

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

    await orchestrator.response_handler.handle("test_user", "test_session", response)

    mock_dependencies["workflow_engine"].transition.assert_not_called()


@pytest.mark.trio
async def test_process_message_propagates_exceptions(orchestrator, mock_dependencies):
    """Test that process_message propagates helper exceptions."""
    mock_dependencies["workflow_engine"].get_user_state.return_value = (
        WorkflowState.INTAKE_IN_PROGRESS
    )
    orchestrator.session_lifecycle.create_session = AsyncMock(
        return_value="session_123"
    )
    orchestrator.conversation_manager.add_message = AsyncMock()
    orchestrator.conversation_manager.get_context = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    with pytest.raises(RuntimeError, match="boom"):
        async for _ in orchestrator.process_message("user_123", "hi", None):
            pass


@pytest.mark.trio
async def test_create_therapy_plan_success(orchestrator, mock_dependencies):
    """Test successful therapy plan creation via orchestrator."""
    # Setup mocks
    mock_db_service = MagicMock()
    mock_db_service.get_user_profile = AsyncMock()
    mock_db_service.get_latest_therapy_plan = AsyncMock()
    mock_db_service.save_therapy_plan = AsyncMock()
    mock_db_service.update_user_profile = AsyncMock()
    mock_style_service = MagicMock()
    mock_reflection_agent = MagicMock()
    mock_reflection_agent.create_initial_plan_with_style = AsyncMock()

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
        updated_at=datetime.now(),
    )
    mock_db_service.get_user_profile.return_value = profile
    mock_db_service.get_latest_therapy_plan.return_value = None
    intake_session = MagicMock()
    orchestrator.session_lifecycle.find_intake_sessions = AsyncMock(
        return_value=[intake_session]
    )
    orchestrator._get_or_create_agent = AsyncMock(return_value=mock_reflection_agent)
    plan = TherapyPlan(
        plan_id="plan_123",
        user_id="test_user",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        plan_details={},
        initial_goals=["Stabilize presenting concerns"],
        current_progress="Baseline established",
        planned_interventions=["Supportive listening"],
        version=1,
        selected_therapy_style="freud",
    )
    mock_reflection_agent.create_initial_plan_with_style.return_value = plan

    # Create therapy plan
    plan = await orchestrator.create_therapy_plan("test_user", "freud")

    # Assertions
    assert plan.user_id == "test_user"
    assert plan.version == 1
    assert plan.selected_therapy_style == "freud"
    assert mock_reflection_agent.create_initial_plan_with_style.called
    mock_dependencies["workflow_engine"].transition.assert_called_once_with(
        "test_user", WorkflowState.PLAN_COMPLETE
    )


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
    mock_db_service = MagicMock()
    mock_db_service.get_user_profile = AsyncMock()
    mock_db_service.get_latest_therapy_plan = AsyncMock()
    mock_db_service.save_therapy_plan = AsyncMock()
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
        updated_at=datetime.now(),
    )
    mock_db_service.get_user_profile.return_value = profile

    # Mock existing plan
    existing_plan = TherapyPlan(
        plan_id="existing_plan_id",
        user_id="test_user",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        plan_details={},
        initial_goals=["Stabilize presenting concerns"],
        current_progress="Baseline established",
        planned_interventions=["Supportive listening"],
        version=1,
        selected_therapy_style="freud",
    )
    mock_db_service.get_latest_therapy_plan.return_value = existing_plan

    # Try to create plan - should return existing
    plan = await orchestrator.create_therapy_plan("test_user", "freud")

    # Should return same plan without saving
    assert plan.plan_id == "existing_plan_id"
    assert plan.version == 1
    mock_db_service.save_therapy_plan.assert_not_called()
    mock_dependencies["workflow_engine"].transition.assert_not_called()
