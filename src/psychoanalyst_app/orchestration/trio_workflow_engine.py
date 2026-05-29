"""
Trio-native workflow engine for managing therapy workflow state transitions.

This is a pure Trio version of WorkflowEngine using TrioDatabaseService.
"""

import logging

from psychoanalyst_app.exceptions import InvalidStateTransitionError
from psychoanalyst_app.models.data_models import UserStatus
from psychoanalyst_app.orchestration.models import WorkflowEvent, WorkflowState
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioWorkflowEngine:
    """
    Trio-native state machine for therapy workflow management.

    This class manages the progression of users through different
    stages of the therapy workflow, from intake through assessment
    to therapy sessions and reflection.
    """

    # Mapping from workflow states to agent types
    STATE_AGENT_MAP: dict[WorkflowState, str] = {
        WorkflowState.NEW: "INTAKE",
        WorkflowState.INTAKE_IN_PROGRESS: "INTAKE",
        WorkflowState.INTAKE_COMPLETE: "ASSESSMENT",
        WorkflowState.ASSESSMENT_IN_PROGRESS: "ASSESSMENT",
        WorkflowState.ASSESSMENT_COMPLETE: "PSYCHOANALYST",
        WorkflowState.INITIAL_PLAN_COMPLETE: "PSYCHOANALYST",
        WorkflowState.THERAPY_IN_PROGRESS: "PSYCHOANALYST",
        WorkflowState.PLAN_UPDATE_IN_PROGRESS: "REFLECTION",
        WorkflowState.REFLECTION_IN_PROGRESS: "REFLECTION",
        WorkflowState.PLAN_COMPLETE: "PSYCHOANALYST",
    }

    # Valid state transitions
    VALID_TRANSITIONS: dict[WorkflowState, list[WorkflowState]] = {
        WorkflowState.NEW: [WorkflowState.INTAKE_IN_PROGRESS],
        WorkflowState.INTAKE_IN_PROGRESS: [
            WorkflowState.INTAKE_COMPLETE,
            WorkflowState.INTAKE_IN_PROGRESS,  # Allow staying in progress
        ],
        WorkflowState.INTAKE_COMPLETE: [WorkflowState.ASSESSMENT_IN_PROGRESS],
        WorkflowState.ASSESSMENT_IN_PROGRESS: [
            WorkflowState.ASSESSMENT_COMPLETE,
            WorkflowState.ASSESSMENT_IN_PROGRESS,  # Allow staying in progress
        ],
        WorkflowState.ASSESSMENT_COMPLETE: [
            WorkflowState.INITIAL_PLAN_COMPLETE,
        ],
        WorkflowState.INITIAL_PLAN_COMPLETE: [
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowState.INITIAL_PLAN_COMPLETE,
        ],
        WorkflowState.THERAPY_IN_PROGRESS: [
            WorkflowState.PLAN_UPDATE_IN_PROGRESS,
            WorkflowState.THERAPY_IN_PROGRESS,  # Allow staying in progress
        ],
        WorkflowState.PLAN_UPDATE_IN_PROGRESS: [
            WorkflowState.PLAN_COMPLETE,
            WorkflowState.PLAN_UPDATE_IN_PROGRESS,  # Allow staying in progress
        ],
        WorkflowState.REFLECTION_IN_PROGRESS: [
            WorkflowState.PLAN_COMPLETE,
            WorkflowState.REFLECTION_IN_PROGRESS,  # Allow staying in progress
        ],
        WorkflowState.PLAN_COMPLETE: [
            WorkflowState.THERAPY_IN_PROGRESS,  # Can resume therapy
            WorkflowState.PLAN_COMPLETE,  # Allow staying in state
        ],
    }

    # Mapping from UserStatus to WorkflowState
    USER_STATUS_TO_WORKFLOW_STATE: dict[UserStatus, WorkflowState] = {
        UserStatus.PROFILE_ONLY: WorkflowState.NEW,
        UserStatus.INTAKE_IN_PROGRESS: WorkflowState.INTAKE_IN_PROGRESS,
        UserStatus.INTAKE_COMPLETE: WorkflowState.INTAKE_COMPLETE,
        UserStatus.ASSESSMENT_IN_PROGRESS: WorkflowState.ASSESSMENT_IN_PROGRESS,
        UserStatus.ASSESSMENT_COMPLETE: WorkflowState.ASSESSMENT_COMPLETE,
        UserStatus.INITIAL_PLAN_COMPLETE: WorkflowState.INITIAL_PLAN_COMPLETE,
        UserStatus.THERAPY_IN_PROGRESS: WorkflowState.THERAPY_IN_PROGRESS,
        UserStatus.PLAN_UPDATE_IN_PROGRESS: WorkflowState.PLAN_UPDATE_IN_PROGRESS,
        UserStatus.REFLECTION_IN_PROGRESS: WorkflowState.REFLECTION_IN_PROGRESS,
        UserStatus.PLAN_COMPLETE: WorkflowState.PLAN_COMPLETE,
    }

    # Mapping from WorkflowState to UserStatus (for persistence)
    WORKFLOW_STATE_TO_USER_STATUS: dict[WorkflowState, UserStatus] = {
        WorkflowState.NEW: UserStatus.PROFILE_ONLY,
        WorkflowState.INTAKE_IN_PROGRESS: UserStatus.INTAKE_IN_PROGRESS,
        WorkflowState.INTAKE_COMPLETE: UserStatus.INTAKE_COMPLETE,
        WorkflowState.ASSESSMENT_IN_PROGRESS: UserStatus.ASSESSMENT_IN_PROGRESS,
        WorkflowState.ASSESSMENT_COMPLETE: UserStatus.ASSESSMENT_COMPLETE,
        WorkflowState.INITIAL_PLAN_COMPLETE: UserStatus.INITIAL_PLAN_COMPLETE,
        WorkflowState.THERAPY_IN_PROGRESS: UserStatus.THERAPY_IN_PROGRESS,
        WorkflowState.PLAN_UPDATE_IN_PROGRESS: UserStatus.PLAN_UPDATE_IN_PROGRESS,
        WorkflowState.REFLECTION_IN_PROGRESS: UserStatus.REFLECTION_IN_PROGRESS,
        WorkflowState.PLAN_COMPLETE: UserStatus.PLAN_COMPLETE,
    }

    def __init__(self, trio_db_service: TrioDatabaseService):
        """
        Initialize the Trio workflow engine.

        Args:
            trio_db_service: Trio database service for state persistence
        """
        self.db_service = trio_db_service

    async def get_user_state(self, user_id: str) -> WorkflowState:
        """
        Get current workflow state for a user.

        Args:
            user_id: User identifier

        Returns:
            Current workflow state

        Raises:
            ValueError: If user not found or invalid status
        """
        user_profile = await self.db_service.get_user_profile(user_id)
        if not user_profile:
            # New user - return NEW state
            return WorkflowState.NEW

        user_status = user_profile.status
        workflow_state = self.USER_STATUS_TO_WORKFLOW_STATE.get(user_status)

        if workflow_state is None:
            logger.error(f"Invalid user status: {user_status}")
            raise ValueError(f"Invalid user status: {user_status}")

        logger.info(f"User {user_id} state: {workflow_state}")
        return workflow_state

    def get_current_agent(self, state: WorkflowState) -> str:
        """
        Determine which agent should handle the current state.

        Args:
            state: Current workflow state

        Returns:
            Agent type string (e.g., "INTAKE", "ASSESSMENT", etc.)
        """
        agent_type = self.STATE_AGENT_MAP.get(state)
        if not agent_type:
            logger.error(f"No agent mapped for state: {state}")
            raise ValueError(f"No agent mapped for state: {state}")

        logger.debug(f"State {state} → Agent {agent_type}")
        return agent_type

    async def transition(
        self,
        user_id: str,
        new_state: WorkflowState,
        event: WorkflowEvent | None = None,
    ) -> None:
        """
        Transition user to a new workflow state.

        Args:
            user_id: User identifier
            new_state: Target workflow state
            event: Optional event triggering the transition

        Raises:
            InvalidStateTransitionError: If transition is not valid
        """
        current_state = await self.get_user_state(user_id)

        if not self.can_transition(current_state, new_state):
            error_msg = (
                f"Invalid transition from {current_state} to {new_state}"
                f"{f' (event: {event})' if event else ''}"
            )
            logger.error(error_msg)
            raise InvalidStateTransitionError(error_msg)

        logger.info(f"Transitioning user {user_id}: {current_state} → {new_state}")

        # Map workflow state to user status for persistence
        user_status = self.WORKFLOW_STATE_TO_USER_STATUS.get(new_state)
        if user_status is None:
            logger.error(f"Cannot map workflow state {new_state} to user status")
            raise ValueError(f"Cannot map workflow state {new_state} to user status")

        # Update database
        await self.db_service.update_user_status(user_id, user_status.value)

        logger.info(
            f"User {user_id} transitioned to {new_state} (status: {user_status})"
        )

    def can_transition(
        self, from_state: WorkflowState, to_state: WorkflowState
    ) -> bool:
        """
        Check if a state transition is valid.

        Args:
            from_state: Current state
            to_state: Target state

        Returns:
            True if transition is valid, False otherwise
        """
        valid_targets = self.VALID_TRANSITIONS.get(from_state, [])
        is_valid = to_state in valid_targets

        logger.debug(
            f"Transition check: {from_state} → {to_state} = {is_valid}"
            f" (valid targets: {valid_targets})"
        )

        return is_valid

    def get_next_state(
        self, current_state: WorkflowState, event: WorkflowEvent
    ) -> WorkflowState:
        """
        Determine next state based on current state and event.

        Args:
            current_state: Current workflow state
            event: Event triggering transition

        Returns:
            Next workflow state

        Raises:
            InvalidStateTransitionError: If no valid transition exists
        """
        # Event → State mapping
        event_state_map = {
            WorkflowEvent.START_INTAKE: WorkflowState.INTAKE_IN_PROGRESS,
            WorkflowEvent.COMPLETE_INTAKE: WorkflowState.INTAKE_COMPLETE,
            WorkflowEvent.START_ASSESSMENT: WorkflowState.ASSESSMENT_IN_PROGRESS,
            WorkflowEvent.COMPLETE_ASSESSMENT: WorkflowState.ASSESSMENT_COMPLETE,
            WorkflowEvent.START_THERAPY: WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowEvent.COMPLETE_SESSION: WorkflowState.PLAN_UPDATE_IN_PROGRESS,
            WorkflowEvent.START_REFLECTION: WorkflowState.PLAN_UPDATE_IN_PROGRESS,
            WorkflowEvent.COMPLETE_REFLECTION: WorkflowState.PLAN_COMPLETE,
            WorkflowEvent.RESUME_THERAPY: WorkflowState.THERAPY_IN_PROGRESS,
        }

        next_state = event_state_map.get(event)
        if next_state is None:
            logger.error(f"No state mapped for event: {event}")
            raise ValueError(f"No state mapped for event: {event}")

        if not self.can_transition(current_state, next_state):
            raise InvalidStateTransitionError(
                f"Cannot transition from {current_state} to {next_state} on event {event}"
            )

        return next_state
