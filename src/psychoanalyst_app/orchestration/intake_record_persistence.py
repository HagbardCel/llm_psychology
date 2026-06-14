"""Persistence helper for structured intake records."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from psychoanalyst_app.models.intake_record import IntakeRecord

logger = logging.getLogger(__name__)


async def update_intake_record(
    conversation_manager,
    session_id: str,
    record: IntakeRecord | dict[str, Any],
) -> None:
    """Persist a structured intake record through the existing session store."""
    try:
        typed_record = (
            record
            if isinstance(record, IntakeRecord)
            else IntakeRecord.model_validate(record)
        )
    except ValidationError:
        logger.warning("Ignoring invalid intake_record payload", exc_info=True)
        return

    updated_at = datetime.now()
    if session_id in conversation_manager.active_contexts:
        context = conversation_manager.active_contexts[session_id]
        context.intake_record = typed_record
        context.intake_record_updated_at = updated_at

    session = await conversation_manager.db_service.get_session(session_id)
    if not session:
        logger.warning("Session not found for intake record update: %s", session_id)
        return
    session.intake_record = typed_record
    session.intake_record_updated_at = updated_at
    saved = await conversation_manager.db_service.save_session(session)
    if not saved:
        logger.warning(
            "Did not persist intake record for session %s (immutable/enriched)",
            session_id,
        )
