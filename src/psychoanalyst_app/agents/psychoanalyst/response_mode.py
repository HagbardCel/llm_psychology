"""Response-mode decision helpers for psychoanalyst agent."""

from __future__ import annotations

from psychoanalyst_app.models.data_models import UserStatus
from psychoanalyst_app.orchestration.models import WorkflowEvent


def resolve_response_mode(
    context,
    *,
    should_offer_extension: bool,
) -> tuple[str, WorkflowEvent | None]:
    """Resolve next action/workflow event from session timing and user status."""
    if context.user_profile.status in (
        UserStatus.ASSESSMENT_COMPLETE,
        UserStatus.INITIAL_PLAN_COMPLETE,
        UserStatus.PLAN_COMPLETE,
    ):
        return ("transition", WorkflowEvent.START_THERAPY)
    if context.is_time_up:
        return ("transition", WorkflowEvent.COMPLETE_SESSION)
    if should_offer_extension:
        return ("offer_extension", None)
    return ("continue", None)
