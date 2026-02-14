"""Conversation context bootstrap helpers."""

from __future__ import annotations

import logging

from psychoanalyst_app.orchestration.models import ConversationContext

logger = logging.getLogger(__name__)


async def load_conversation_context(*, db_service, config, session_id: str):
    """Load context from persistence into ConversationContext object."""
    session = await db_service.get_session(session_id)
    if not session:
        raise ValueError(f"Session not found: {session_id}")

    user_profile = await db_service.get_user_profile(session.user_id)
    if not user_profile:
        raise ValueError(f"User profile not found: {session.user_id}")

    therapy_plan = None
    try:
        therapy_plan = await db_service.get_latest_therapy_plan(session.user_id)
    except Exception as exc:
        logger.warning("No therapy plan found for user %s: %s", session.user_id, exc)

    return ConversationContext(
        session_id=session_id,
        user_profile=user_profile,
        therapy_plan=therapy_plan,
        message_history=session.transcript,
        topics_covered=[topic.name for topic in session.topics],
        session_start_time=session.timestamp,
        duration_minutes=config.SESSION_DURATION_MINUTES,
    )
