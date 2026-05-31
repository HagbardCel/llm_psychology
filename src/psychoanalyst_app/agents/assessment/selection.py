"""Selection/continuation parsing and response builders for assessment flow."""

from __future__ import annotations

import logging

from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    direct_agent_response,
)

logger = logging.getLogger(__name__)


def parse_continuation_choice(message: str) -> str | None:
    """Parse a user message to determine whether to finish or continue."""
    message = message.lower()

    finish_keywords = [
        "finish",
        "stop",
        "end",
        "done",
        "later",
        "next time",
        "option 1",
        "1",
        "first",
        "reflect",
    ]
    for keyword in finish_keywords:
        if keyword in message:
            return "finish"

    continue_keywords = [
        "continue",
        "start",
        "begin",
        "now",
        "yes",
        "go ahead",
        "option 2",
        "2",
        "second",
        "therapy",
    ]
    for keyword in continue_keywords:
        if keyword in message:
            return "continue"

    return None


def parse_style_selection(message: str, available_styles: list[str]) -> str | None:
    """Parse a user message to identify a selected therapy style."""
    message = message.lower()
    logger.debug(
        "Assessment selection parse: message=%r styles=%s",
        message,
        available_styles,
    )

    for style in available_styles:
        if style.lower() in message:
            logger.debug("Assessment selection matched style: %s", style)
            return style

    logger.debug("Assessment selection: no style found")
    return None


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
