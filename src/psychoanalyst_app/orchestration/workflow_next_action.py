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

DEFAULT_PROFILE_FIELDS = ["name", "primary_language", "session_mode"]
DEFAULT_PROFILE_PROMPT = "Complete your profile so we can tailor the next steps."
DEFAULT_PROFILE_DEFAULTS = {
    "primary_language": "English",
    "session_mode": "virtual",
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
        )

    if workflow_state == WorkflowState.INTAKE_IN_PROGRESS:
        return _start_session_action(
            user_id,
            workflow_state,
            title="Continue your intake session",
            prompt=_session_prompt(workflow_state, session),
        )

    if workflow_state == WorkflowState.ASSESSMENT_IN_PROGRESS:
        return _wait_action(
            user_id,
            workflow_state,
            prompt="Assessment in progress. We'll notify you when it's ready.",
        )

    if workflow_state == WorkflowState.INTAKE_COMPLETE:
        return _wait_action(
            user_id,
            workflow_state,
            prompt="Assessment in progress. We'll notify you when it's ready.",
        )

    if workflow_state == WorkflowState.ASSESSMENT_COMPLETE:
        if plan and plan.selected_therapy_style:
            return _continue_therapy_action(user_id, workflow_state)
        return WorkflowNextActionDTO(
            user_id=user_id,
            workflow_state=workflow_state,
            required_action=RequiredWorkflowAction.SELECT_THERAPY_STYLE,
            required_fields=["selected_therapy_style"],
            defaults=None,
            prompt="Select a therapy style to generate your personalized plan.",
            blocking=True,
            timestamp=datetime.utcnow(),
        )

    if workflow_state in (
        WorkflowState.THERAPY_IN_PROGRESS,
        WorkflowState.PLAN_COMPLETE,
    ):
        return _continue_therapy_action(user_id, workflow_state)

    if workflow_state == WorkflowState.REFLECTION_IN_PROGRESS:
        return _wait_action(
            user_id,
            workflow_state,
            prompt="Reflection in progress. We'll notify you when it's ready.",
        )

    # Default fallback when state is NEW but profile already exists
    return _start_session_action(
        user_id,
        workflow_state,
        title="Continue your intake session",
        prompt=_session_prompt(workflow_state, session),
    )


def _profile_defaults(profile: UserProfile | None) -> dict[str, str]:
    defaults = {}
    if profile:
        if profile.name:
            defaults["name"] = profile.name
        if profile.primary_language:
            defaults["primary_language"] = profile.primary_language
        if profile.session_mode:
            defaults["session_mode"] = profile.session_mode

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
    user_id: str, state: WorkflowState, *, title: str, prompt: str
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
    )


def _wait_action(user_id: str, state: WorkflowState, *, prompt: str) -> WorkflowNextActionDTO:
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
    )


def _continue_therapy_action(user_id: str, state: WorkflowState) -> WorkflowNextActionDTO:
    """Helper for therapy continuation prompts."""
    return WorkflowNextActionDTO(
        user_id=user_id,
        workflow_state=state,
        required_action=RequiredWorkflowAction.CONTINUE_THERAPY,
        required_fields=[],
        defaults=None,
        prompt="Resume your therapy session or start a new one whenever you're ready.",
        blocking=False,
        timestamp=datetime.utcnow(),
    )
