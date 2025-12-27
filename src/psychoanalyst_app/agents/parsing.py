"""Shared parsing helpers for agent inputs."""

from __future__ import annotations

import logging

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
