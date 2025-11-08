"""
Unit tests for WorkflowEngine.

Tests the state machine, transitions, and agent mapping.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from src.orchestration.workflow_engine import WorkflowEngine
from src.orchestration.models import WorkflowState, WorkflowEvent
from src.exceptions import InvalidStateTransitionError


@pytest.fixture
def mock_db_service():
    """Create a mock database service."""
    db = Mock()
    db.get_user_workflow_state = Mock(return_value=WorkflowState.NEW)
    db.update_user_workflow_state = Mock()
    return db


@pytest.fixture
def workflow_engine(mock_db_service):
    """Create a WorkflowEngine instance with mocked dependencies."""
    return WorkflowEngine(mock_db_service)


class TestWorkflowEngineInitialization:
    """Test WorkflowEngine initialization."""

    def test_initialization(self, workflow_engine, mock_db_service):
        """Test that WorkflowEngine initializes correctly."""
        assert workflow_engine.db_service == mock_db_service
        assert workflow_engine.state_transitions is not None
        assert len(workflow_engine.state_transitions) > 0


class TestGetUserState:
    """Test getting user workflow state."""

    @pytest.mark.asyncio
    async def test_get_user_state_existing(self, workflow_engine, mock_db_service):
        """Test getting state for existing user."""
        mock_db_service.get_user_workflow_state.return_value = WorkflowState.INTAKE_COMPLETE

        state = await workflow_engine.get_user_state("user123")

        assert state == WorkflowState.INTAKE_COMPLETE
        mock_db_service.get_user_workflow_state.assert_called_once_with("user123")

    @pytest.mark.asyncio
    async def test_get_user_state_new_user(self, workflow_engine, mock_db_service):
        """Test getting state for new user returns NEW."""
        mock_db_service.get_user_workflow_state.return_value = None

        state = await workflow_engine.get_user_state("new_user")

        assert state == WorkflowState.NEW

    @pytest.mark.asyncio
    async def test_get_user_state_string_conversion(self, workflow_engine, mock_db_service):
        """Test that string states are converted to enum."""
        mock_db_service.get_user_workflow_state.return_value = "therapy_in_progress"

        state = await workflow_engine.get_user_state("user123")

        assert state == WorkflowState.THERAPY_IN_PROGRESS
        assert isinstance(state, WorkflowState)


class TestGetCurrentAgent:
    """Test agent mapping from workflow state."""

    def test_get_current_agent_new(self, workflow_engine):
        """Test agent for NEW state."""
        agent = workflow_engine.get_current_agent(WorkflowState.NEW)
        assert agent == "INTAKE"

    def test_get_current_agent_intake_in_progress(self, workflow_engine):
        """Test agent for INTAKE_IN_PROGRESS state."""
        agent = workflow_engine.get_current_agent(WorkflowState.INTAKE_IN_PROGRESS)
        assert agent == "INTAKE"

    def test_get_current_agent_intake_complete(self, workflow_engine):
        """Test agent for INTAKE_COMPLETE state."""
        agent = workflow_engine.get_current_agent(WorkflowState.INTAKE_COMPLETE)
        assert agent == "ASSESSMENT"

    def test_get_current_agent_assessment_complete(self, workflow_engine):
        """Test agent for ASSESSMENT_COMPLETE state."""
        agent = workflow_engine.get_current_agent(WorkflowState.ASSESSMENT_COMPLETE)
        assert agent == "PSYCHOANALYST"

    def test_get_current_agent_therapy_in_progress(self, workflow_engine):
        """Test agent for THERAPY_IN_PROGRESS state."""
        agent = workflow_engine.get_current_agent(WorkflowState.THERAPY_IN_PROGRESS)
        assert agent == "PSYCHOANALYST"

    def test_get_current_agent_reflection(self, workflow_engine):
        """Test agent for REFLECTION_IN_PROGRESS state."""
        agent = workflow_engine.get_current_agent(WorkflowState.REFLECTION_IN_PROGRESS)
        assert agent == "REFLECTION"

    def test_get_current_agent_plan_complete(self, workflow_engine):
        """Test agent for PLAN_COMPLETE state."""
        agent = workflow_engine.get_current_agent(WorkflowState.PLAN_COMPLETE)
        assert agent == "PSYCHOANALYST"


class TestCanTransition:
    """Test transition validation."""

    def test_can_transition_valid_new_to_intake(self, workflow_engine):
        """Test valid transition from NEW to INTAKE_IN_PROGRESS."""
        assert workflow_engine.can_transition(
            WorkflowState.NEW,
            WorkflowState.INTAKE_IN_PROGRESS
        ) is True

    def test_can_transition_valid_intake_to_complete(self, workflow_engine):
        """Test valid transition from INTAKE_IN_PROGRESS to INTAKE_COMPLETE."""
        assert workflow_engine.can_transition(
            WorkflowState.INTAKE_IN_PROGRESS,
            WorkflowState.INTAKE_COMPLETE
        ) is True

    def test_can_transition_valid_intake_complete_to_assessment(self, workflow_engine):
        """Test valid transition from INTAKE_COMPLETE to ASSESSMENT_IN_PROGRESS."""
        assert workflow_engine.can_transition(
            WorkflowState.INTAKE_COMPLETE,
            WorkflowState.ASSESSMENT_IN_PROGRESS
        ) is True

    def test_can_transition_valid_assessment_to_therapy(self, workflow_engine):
        """Test valid transition from ASSESSMENT_COMPLETE to THERAPY_IN_PROGRESS."""
        assert workflow_engine.can_transition(
            WorkflowState.ASSESSMENT_COMPLETE,
            WorkflowState.THERAPY_IN_PROGRESS
        ) is True

    def test_can_transition_valid_therapy_to_reflection(self, workflow_engine):
        """Test valid transition from THERAPY_IN_PROGRESS to REFLECTION_IN_PROGRESS."""
        assert workflow_engine.can_transition(
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowState.REFLECTION_IN_PROGRESS
        ) is True

    def test_can_transition_valid_reflection_to_plan_complete(self, workflow_engine):
        """Test valid transition from REFLECTION_IN_PROGRESS to PLAN_COMPLETE."""
        assert workflow_engine.can_transition(
            WorkflowState.REFLECTION_IN_PROGRESS,
            WorkflowState.PLAN_COMPLETE
        ) is True

    def test_can_transition_invalid_skip_intake(self, workflow_engine):
        """Test invalid transition skipping intake."""
        assert workflow_engine.can_transition(
            WorkflowState.NEW,
            WorkflowState.ASSESSMENT_IN_PROGRESS
        ) is False

    def test_can_transition_invalid_backward(self, workflow_engine):
        """Test invalid backward transition."""
        assert workflow_engine.can_transition(
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowState.INTAKE_IN_PROGRESS
        ) is False

    def test_can_transition_same_state(self, workflow_engine):
        """Test transition to same state (should be allowed for idempotency)."""
        # Same state transitions should be allowed
        assert workflow_engine.can_transition(
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowState.THERAPY_IN_PROGRESS
        ) is True


class TestTransition:
    """Test state transition execution."""

    @pytest.mark.asyncio
    async def test_transition_success(self, workflow_engine, mock_db_service):
        """Test successful state transition."""
        mock_db_service.get_user_workflow_state.return_value = WorkflowState.NEW

        await workflow_engine.transition(
            "user123",
            WorkflowState.INTAKE_IN_PROGRESS,
            WorkflowEvent.INTAKE_STARTED
        )

        mock_db_service.update_user_workflow_state.assert_called_once_with(
            "user123",
            WorkflowState.INTAKE_IN_PROGRESS
        )

    @pytest.mark.asyncio
    async def test_transition_invalid_raises_error(self, workflow_engine, mock_db_service):
        """Test that invalid transition raises error."""
        mock_db_service.get_user_workflow_state.return_value = WorkflowState.NEW

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            await workflow_engine.transition(
                "user123",
                WorkflowState.THERAPY_IN_PROGRESS,  # Invalid: skipping intake and assessment
                WorkflowEvent.SESSION_STARTED
            )

        assert "Cannot transition from NEW to THERAPY_IN_PROGRESS" in str(exc_info.value)
        mock_db_service.update_user_workflow_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_transition_progression_through_workflow(self, workflow_engine, mock_db_service):
        """Test complete progression through workflow states."""
        # Start at NEW
        mock_db_service.get_user_workflow_state.return_value = WorkflowState.NEW

        # NEW -> INTAKE_IN_PROGRESS
        await workflow_engine.transition(
            "user123",
            WorkflowState.INTAKE_IN_PROGRESS,
            WorkflowEvent.INTAKE_STARTED
        )

        # INTAKE_IN_PROGRESS -> INTAKE_COMPLETE
        mock_db_service.get_user_workflow_state.return_value = WorkflowState.INTAKE_IN_PROGRESS
        await workflow_engine.transition(
            "user123",
            WorkflowState.INTAKE_COMPLETE,
            WorkflowEvent.INTAKE_COMPLETED
        )

        # INTAKE_COMPLETE -> ASSESSMENT_IN_PROGRESS
        mock_db_service.get_user_workflow_state.return_value = WorkflowState.INTAKE_COMPLETE
        await workflow_engine.transition(
            "user123",
            WorkflowState.ASSESSMENT_IN_PROGRESS,
            WorkflowEvent.ASSESSMENT_STARTED
        )

        # ASSESSMENT_IN_PROGRESS -> ASSESSMENT_COMPLETE
        mock_db_service.get_user_workflow_state.return_value = WorkflowState.ASSESSMENT_IN_PROGRESS
        await workflow_engine.transition(
            "user123",
            WorkflowState.ASSESSMENT_COMPLETE,
            WorkflowEvent.ASSESSMENT_COMPLETED
        )

        # ASSESSMENT_COMPLETE -> THERAPY_IN_PROGRESS
        mock_db_service.get_user_workflow_state.return_value = WorkflowState.ASSESSMENT_COMPLETE
        await workflow_engine.transition(
            "user123",
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowEvent.SESSION_STARTED
        )

        # Verify all transitions were saved
        assert mock_db_service.update_user_workflow_state.call_count == 5


class TestGetNextState:
    """Test determining next state based on events."""

    def test_get_next_state_intake_completion(self, workflow_engine):
        """Test next state after intake completion."""
        next_state = workflow_engine.get_next_state(
            WorkflowState.INTAKE_IN_PROGRESS,
            WorkflowEvent.INTAKE_COMPLETED
        )
        assert next_state == WorkflowState.INTAKE_COMPLETE

    def test_get_next_state_assessment_completion(self, workflow_engine):
        """Test next state after assessment completion."""
        next_state = workflow_engine.get_next_state(
            WorkflowState.ASSESSMENT_IN_PROGRESS,
            WorkflowEvent.ASSESSMENT_COMPLETED
        )
        assert next_state == WorkflowState.ASSESSMENT_COMPLETE

    def test_get_next_state_session_start(self, workflow_engine):
        """Test next state when starting therapy session."""
        next_state = workflow_engine.get_next_state(
            WorkflowState.ASSESSMENT_COMPLETE,
            WorkflowEvent.SESSION_STARTED
        )
        assert next_state == WorkflowState.THERAPY_IN_PROGRESS

    def test_get_next_state_reflection_start(self, workflow_engine):
        """Test next state when starting reflection."""
        next_state = workflow_engine.get_next_state(
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowEvent.SESSION_ENDED
        )
        assert next_state == WorkflowState.REFLECTION_IN_PROGRESS
