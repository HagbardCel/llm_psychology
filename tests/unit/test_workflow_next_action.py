"""Unit tests for the workflow next action resolver."""

from datetime import datetime

from psychoanalyst_app.models.domain import TherapyPlan, UserProfile, UserStatus
from psychoanalyst_app.models.http import RequiredWorkflowAction
from psychoanalyst_app.orchestration.models import SessionInfo, WorkflowState
from psychoanalyst_app.orchestration.workflow_next_action import resolve_next_action


def _complete_profile(user_id: str = "user-123") -> UserProfile:
    """Helper to build a profile that satisfies completeness rules."""
    now = datetime.utcnow()
    return UserProfile(
        user_id=user_id,
        name="Alice",
        date_of_birth=now,
        gender="female",
        cultural_background="N/A",
        primary_language="English",
        profession="Developer",
        status=UserStatus.INTAKE_IN_PROGRESS,
        parents=None,
        siblings=None,
        family_atmosphere=None,
        significant_events=None,
        education=None,
        work_history=None,
        relationship_to_work=None,
        relationships=None,
        social_context=None,
        current_situation=None,
        preferred_school=None,
        boundary_notes=None,
        frame_notes=None,
        created_at=now,
        updated_at=now,
    )


def _therapy_plan(style: str = "freud") -> TherapyPlan:
    """Helper to build a minimal therapy plan."""
    now = datetime.utcnow()
    return TherapyPlan(
        plan_id="plan-123",
        user_id="user-123",
        created_at=now,
        updated_at=now,
        version=1,
        selected_therapy_style=style,
        focus="test",
        initial_goals=["Goal"],
        current_progress="progress",
        planned_interventions=["intervention"],
        status="active",
    )


def test_requires_profile_completion_when_missing():
    """The resolver should ask for profile completion if the profile is missing."""
    action = resolve_next_action(
        user_id="user-1",
        workflow_state=WorkflowState.NEW,
        profile=None,
        plan=None,
    )

    assert action.required_action == RequiredWorkflowAction.COMPLETE_PROFILE
    assert "name" in action.required_fields
    assert action.prompt is not None


def test_starts_session_during_intake_progress():
    """Users in intake progress should be prompted to start or resume intake."""
    profile = _complete_profile()
    action = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.INTAKE_IN_PROGRESS,
        profile=profile,
        plan=None,
    )

    assert action.required_action == RequiredWorkflowAction.START_INTAKE
    assert not action.blocking


def test_waits_during_assessment_in_progress():
    """Assessment runs in the backend; clients should wait."""
    profile = _complete_profile()
    action = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.ASSESSMENT_IN_PROGRESS,
        profile=profile,
        plan=None,
    )

    assert action.required_action == RequiredWorkflowAction.WAIT
    assert action.blocking
    assert "Assessment in progress" in (action.prompt or "")


def test_equivalent_actions_have_stable_state_signature():
    """Fresh timestamps must not prevent workflow display deduplication."""
    profile = _complete_profile()

    first = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.ASSESSMENT_IN_PROGRESS,
        profile=profile,
        plan=None,
    )
    second = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.ASSESSMENT_IN_PROGRESS,
        profile=profile,
        plan=None,
    )

    assert first.state_signature
    assert first.state_signature == second.state_signature


def test_waits_after_intake_complete():
    """Intake completion should return a wait action while assessment runs."""
    profile = _complete_profile()
    action = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.INTAKE_COMPLETE,
        profile=profile,
        plan=None,
    )

    assert action.required_action == RequiredWorkflowAction.WAIT
    assert action.blocking
    assert "Assessment in progress" in (action.prompt or "")


def test_selects_style_after_assessment_complete():
    """The resolver should prepare the select therapy style action when no plan exists."""
    profile = _complete_profile()
    action = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.ASSESSMENT_COMPLETE,
        profile=profile,
        plan=None,
    )

    assert action.required_action == RequiredWorkflowAction.SELECT_THERAPY_STYLE
    assert action.blocking
    assert action.required_fields == ["selected_therapy_style"]


def test_starts_initial_therapy_and_continues_after_plan_update():
    """Initial therapy requires a deliberate start; recurring therapy resumes."""
    profile = _complete_profile()
    plan = _therapy_plan()
    initial_action = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.INITIAL_PLAN_COMPLETE,
        profile=profile,
        plan=plan,
    )
    recurring_action = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.PLAN_UPDATE_COMPLETE,
        profile=profile,
        plan=plan,
    )

    assert initial_action.required_action == RequiredWorkflowAction.START_THERAPY
    assert "selected therapy style is ready" in (initial_action.prompt or "").lower()
    assert not initial_action.blocking
    assert recurring_action.required_action == RequiredWorkflowAction.CONTINUE_THERAPY
    assert "session reflection is complete" in (recurring_action.prompt or "")
    assert not recurring_action.blocking


def test_waits_during_plan_update_in_progress():
    """Post-session plan updates run in the backend while clients wait."""
    profile = _complete_profile()
    action = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.PLAN_UPDATE_IN_PROGRESS,
        profile=profile,
        plan=_therapy_plan(),
    )

    assert action.required_action == RequiredWorkflowAction.WAIT
    assert action.blocking
    assert "Session reflection in progress" in (action.prompt or "")


def test_requires_explicit_retry_after_plan_update_failure():
    """Failed reflection must block therapy until the user retries it."""
    profile = _complete_profile()
    action = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.PLAN_UPDATE_FAILED,
        profile=profile,
        plan=_therapy_plan(),
    )

    assert action.required_action == RequiredWorkflowAction.RETRY_PLAN_UPDATE
    assert action.blocking
    assert "could not be saved" in (action.prompt or "")


def test_session_info_influences_prompt():
    """Session information should be referenced when available."""
    profile = _complete_profile()
    session = SessionInfo(
        session_id="sess-1",
        agent_type="INTAKE",
        workflow_state=WorkflowState.INTAKE_IN_PROGRESS,
        created_at=datetime.utcnow(),
        user_id=profile.user_id,
    )

    action = resolve_next_action(
        user_id=profile.user_id,
        workflow_state=WorkflowState.INTAKE_IN_PROGRESS,
        profile=profile,
        plan=None,
        session=session,
    )

    assert session.session_id in action.prompt
