"""Session policy helpers: time-window, topic-depth, and response-mode resolution."""

from __future__ import annotations

from psychoanalyst_app.models.domain import UserStatus
from psychoanalyst_app.orchestration.models import WorkflowEvent


def should_offer_extension(context, *, in_deep_topic: bool) -> bool:
    """Check if session extension should be offered."""
    return (
        context.time_remaining_minutes <= 5
        and context.can_extend
        and context.time_remaining_minutes > 0
        and not in_deep_topic
    )


def is_in_deep_topic(context) -> bool:
    """Conservative fallback used when deep-topic classification is unavailable."""
    _ = context
    return False


def resolve_response_mode(
    context,
    *,
    should_offer_extension: bool,
) -> tuple[str, WorkflowEvent | None]:
    """Resolve next action/workflow event from session timing and user status."""
    if context.user_profile.status in (
        UserStatus.ASSESSMENT_COMPLETE,
        UserStatus.INITIAL_PLAN_COMPLETE,
        UserStatus.PLAN_UPDATE_COMPLETE,
    ):
        return ("transition", WorkflowEvent.START_THERAPY)
    if context.is_time_up:
        return ("transition", WorkflowEvent.COMPLETE_SESSION)
    if should_offer_extension:
        return ("offer_extension", None)
    return ("continue", None)
