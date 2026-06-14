"""Persistence helper for structured intake records."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


async def update_intake_record(
    conversation_manager,
    session_id: str,
    record: dict[str, Any],
) -> None:
    """Persist a structured intake record through the existing session store."""
    if session_id in conversation_manager.active_contexts:
        conversation_manager.active_contexts[session_id].intake_record = record

    session = await conversation_manager.db_service.get_session(session_id)
    if not session:
        logger.warning("Session not found for intake record update: %s", session_id)
        return
    session.intake_record = record
    session.intake_record_updated_at = datetime.now()
    saved = await conversation_manager.db_service.save_session(session)
    if not saved:
        logger.warning(
            "Did not persist intake record for session %s (immutable/enriched)",
            session_id,
        )
