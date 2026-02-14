"""Selection/continuation response builders for assessment flow."""

from __future__ import annotations

from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    direct_agent_response,
)


def build_continuation_choice_response(choice: str | None) -> AgentResponse:
    """Build direct response for continuation menu choices."""
    if choice == "finish":
        return direct_agent_response(
            content="That sounds like a good plan. Take your time to "
            "reflect on what we've discussed today. I look forward to our first "
            "therapy session together. Take care!",
            next_action="end_session",
            metadata={"session_ended": True},
        )

    if choice == "continue":
        return direct_agent_response(
            content="Wonderful! Let's begin our first therapy session. "
            "I'm here to support you.",
            next_action="start_therapy",
            workflow_event=None,
            metadata={"new_session_required": True},
        )

    return direct_agent_response(
        content="I'm not sure which option you'd prefer. Would you "
        "like to finish for today (option 1) or continue with our first therapy "
        "session now (option 2)?",
        next_action="await_continuation_choice",
    )


def build_selection_pending_response(selected_style: str) -> AgentResponse:
    """Build response when selection happens outside message parsing flow."""
    content = (
        "Thanks for sharing your preference. "
        "Therapy style selection is handled through the workflow UI. "
        "Please choose your style there so the backend can create your plan."
    )
    return direct_agent_response(
        content=content,
        next_action="await_selection",
        metadata={"selected_style": selected_style},
    )
