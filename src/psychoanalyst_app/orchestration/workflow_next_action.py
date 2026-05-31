"""Pure resolver for backend workflow next actions."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from psychoanalyst_app.models.api_models import (
    RequiredWorkflowAction,
    WorkflowNextActionDTO,
)
from psychoanalyst_app.models.data_models import TherapyPlan, UserProfile
from psychoanalyst_app.orchestration.agent_output_validators import is_profile_complete
from psychoanalyst_app.orchestration.models import SessionInfo, WorkflowState

DEFAULT_PROFILE_FIELDS = ["name", "primary_language"]
DEFAULT_PROFILE_PROMPT = "Complete your profile so we can tailor the next steps."
DEFAULT_PROFILE_DEFAULTS = {
    "primary_language": "English",
}


def resolve_next_action(
    *,
    user_id: str,
    workflow_state: WorkflowState,
    profile: UserProfile | None,
    plan: TherapyPlan | None,
    session: SessionInfo | None = None,
) -> WorkflowNextActionDTO:
    """
    Build the next action instruction for a user based on workflow context.

    This resolver is deterministic and side-effect free to keep HTTP and WebSocket
    handlers aligned.
    """
    session_id = session.session_id if session else None
    if not profile or not is_profile_complete(profile):
        return WorkflowNextActionDTO(
            user_id=user_id,
            workflow_state=workflow_state,
            required_action=RequiredWorkflowAction.COMPLETE_PROFILE,
            required_fields=DEFAULT_PROFILE_FIELDS,
            defaults=_profile_defaults(profile),
            prompt=DEFAULT_PROFILE_PROMPT,
            blocking=True,
            timestamp=datetime.utcnow(),
            session_id=session_id,
        )

    if workflow_state == WorkflowState.INTAKE_IN_PROGRESS:
        return _start_session_action(
            user_id,
            workflow_state,
            title="Continue your intake session",
            prompt=_session_prompt(workflow_state, session),
            session_id=session_id,
        )

    if workflow_state == WorkflowState.ASSESSMENT_IN_PROGRESS:
        return _wait_action(
            user_id,
            workflow_state,
            prompt="Assessment in progress. We'll notify you when it's ready.",
            session_id=session_id,
        )

    if workflow_state == WorkflowState.INTAKE_COMPLETE:
        return _wait_action(
            user_id,
            workflow_state,
            prompt="Assessment in progress. We'll notify you when it's ready.",
            session_id=session_id,
        )

    if workflow_state == WorkflowState.ASSESSMENT_COMPLETE:
        if plan and plan.selected_therapy_style:
            return _continue_therapy_action(
                user_id, workflow_state, session_id=session_id
            )
        return WorkflowNextActionDTO(
            user_id=user_id,
            workflow_state=workflow_state,
            required_action=RequiredWorkflowAction.SELECT_THERAPY_STYLE,
            required_fields=["selected_therapy_style"],
            defaults=None,
            prompt="Select a therapy style to generate your personalized plan.",
            blocking=True,
            timestamp=datetime.utcnow(),
            session_id=session_id,
        )

    if workflow_state == WorkflowState.INITIAL_PLAN_COMPLETE:
        return _start_therapy_action(user_id, workflow_state, session_id=session_id)

    if workflow_state in (
        WorkflowState.THERAPY_IN_PROGRESS,
        WorkflowState.PLAN_UPDATE_COMPLETE,
    ):
        return _continue_therapy_action(user_id, workflow_state, session_id=session_id)

    if workflow_state in (
        WorkflowState.PLAN_UPDATE_IN_PROGRESS,
        WorkflowState.REFLECTION_IN_PROGRESS,
    ):
        return _wait_action(
            user_id,
            workflow_state,
            prompt="Session reflection in progress. We'll notify you when it's ready.",
            session_id=session_id,
        )

    if workflow_state == WorkflowState.PLAN_UPDATE_FAILED:
        return WorkflowNextActionDTO(
            user_id=user_id,
            workflow_state=workflow_state,
            required_action=RequiredWorkflowAction.RETRY_PLAN_UPDATE,
            required_fields=[],
            defaults=None,
            prompt=(
                "The session reflection could not be saved. Retry the plan update "
                "before starting another therapy session."
            ),
            blocking=True,
            timestamp=datetime.utcnow(),
            session_id=session_id,
        )

    # Default fallback when state is NEW but profile already exists
    return _start_session_action(
        user_id,
        workflow_state,
        title="Continue your intake session",
        prompt=_session_prompt(workflow_state, session),
        session_id=session_id,
    )


def _profile_defaults(profile: UserProfile | None) -> dict[str, str]:
    defaults = {}
    if profile:
        if profile.name:
            defaults["name"] = profile.name
        if profile.primary_language:
            defaults["primary_language"] = profile.primary_language

    for key, value in DEFAULT_PROFILE_DEFAULTS.items():
        defaults.setdefault(key, value)

    return defaults


def _session_prompt(state: WorkflowState, session: SessionInfo | None) -> str:
    if session:
        return (
            f"Session {session.session_id} in state {state.value} needs your next message."
        )
    return f"Start or continue the {state.value.replace('_', ' ')} session."


def _start_session_action(
    user_id: str,
    state: WorkflowState,
    *,
    title: str,
    prompt: str,
    session_id: str | None,
) -> WorkflowNextActionDTO:
    """Helper for intake/assessment start actions."""
    return WorkflowNextActionDTO(
        user_id=user_id,
        workflow_state=state,
        required_action=RequiredWorkflowAction.START_INTAKE,
        required_fields=[],
        defaults=None,
        prompt=prompt,
        blocking=False,
        timestamp=datetime.utcnow(),
        session_id=session_id,
    )


def _wait_action(
    user_id: str, state: WorkflowState, *, prompt: str, session_id: str | None
) -> WorkflowNextActionDTO:
    """Helper for backend-driven wait states."""
    return WorkflowNextActionDTO(
        user_id=user_id,
        workflow_state=state,
        required_action=RequiredWorkflowAction.WAIT,
        required_fields=[],
        defaults=None,
        prompt=prompt,
        blocking=True,
        timestamp=datetime.utcnow(),
        session_id=session_id,
    )


def _continue_therapy_action(
    user_id: str, state: WorkflowState, *, session_id: str | None
) -> WorkflowNextActionDTO:
    """Helper for therapy continuation prompts."""
    if state == WorkflowState.PLAN_UPDATE_COMPLETE:
        prompt = "Your session reflection is complete. Resume therapy whenever you're ready."
    else:
        prompt = "Resume your therapy session or start a new one whenever you're ready."
    return WorkflowNextActionDTO(
        user_id=user_id,
        workflow_state=state,
        required_action=RequiredWorkflowAction.CONTINUE_THERAPY,
        required_fields=[],
        defaults=None,
        prompt=prompt,
        blocking=False,
        timestamp=datetime.utcnow(),
        session_id=session_id,
    )


def _start_therapy_action(
    user_id: str, state: WorkflowState, *, session_id: str | None
) -> WorkflowNextActionDTO:
    """Prompt the client to explicitly begin the first therapy session."""
    return WorkflowNextActionDTO(
        user_id=user_id,
        workflow_state=state,
        required_action=RequiredWorkflowAction.START_THERAPY,
        required_fields=[],
        defaults=None,
        prompt="Your selected therapy style is ready. Start therapy now?",
        blocking=False,
        timestamp=datetime.utcnow(),
        session_id=session_id,
    )
