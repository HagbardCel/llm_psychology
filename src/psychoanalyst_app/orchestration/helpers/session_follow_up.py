"""Background completion for post-session reflection work."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine

logger = logging.getLogger(__name__)

RunReflectionFn = Callable[[str, str], Awaitable[None]]
EmitNextActionFn = Callable[[str, str | None], Awaitable[None]]


async def run_session_end_follow_up(
    user_id: str,
    session_id: str,
    follow_up: RunReflectionFn,
    follow_up_args: tuple[Any, ...],
    workflow_engine: TrioWorkflowEngine,
    emit_next_action: EmitNextActionFn | None,
) -> None:
    """Complete reflection after the client-visible session lifecycle has ended."""
    try:
        await follow_up(*follow_up_args)
    except Exception:
        logger.error(
            "Follow-up job failed for session %s (user=%s)",
            session_id,
            user_id,
            exc_info=True,
        )

    try:
        final_state = await workflow_engine.get_user_state(user_id)
        logger.info(
            "Post-session follow-up finished for session %s in state %s",
            session_id,
            final_state,
        )
    except Exception:
        logger.warning(
            "Failed to refresh workflow state after session end "
            "(user=%s, session=%s)",
            user_id,
            session_id,
            exc_info=True,
        )

    if emit_next_action:
        try:
            await emit_next_action(user_id, session_id)
        except Exception:
            logger.warning(
                "Could not emit workflow next action after follow-up for session %s",
                session_id,
                exc_info=True,
            )
