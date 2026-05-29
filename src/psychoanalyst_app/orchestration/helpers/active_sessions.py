"""Active session tracking and workflow-state session type mapping."""

from __future__ import annotations

from psychoanalyst_app.orchestration.models import WorkflowState


class ActiveSessionRegistry:
    """Track active sessions per user (single concurrent session)."""

    def __init__(self) -> None:
        self._active_sessions: dict[str, str] = {}

    def get_active_session_id(self, user_id: str) -> str | None:
        return self._active_sessions.get(user_id)

    def set_active_session_id(self, user_id: str, session_id: str) -> None:
        self._active_sessions[user_id] = session_id

    def clear_active_session(self, user_id: str, session_id: str | None = None) -> None:
        if session_id is None:
            self._active_sessions.pop(user_id, None)
            return
        if self._active_sessions.get(user_id) == session_id:
            self._active_sessions.pop(user_id, None)

    def is_session_active(self, user_id: str, session_id: str) -> bool:
        return self._active_sessions.get(user_id) == session_id


def session_type_for_workflow_state(state: WorkflowState) -> str:
    """Map workflow state to the session type to resume next."""
    state_map = {
        WorkflowState.NEW: "intake",
        WorkflowState.INTAKE_IN_PROGRESS: "intake",
        WorkflowState.INTAKE_COMPLETE: "assessment",
        WorkflowState.ASSESSMENT_IN_PROGRESS: "assessment",
        WorkflowState.ASSESSMENT_COMPLETE: "therapy",
        WorkflowState.INITIAL_PLAN_COMPLETE: "therapy",
        WorkflowState.THERAPY_IN_PROGRESS: "therapy",
        WorkflowState.PLAN_UPDATE_IN_PROGRESS: "therapy",
        WorkflowState.REFLECTION_IN_PROGRESS: "therapy",
        WorkflowState.PLAN_UPDATE_COMPLETE: "therapy",
    }
    return state_map.get(state, "therapy")
