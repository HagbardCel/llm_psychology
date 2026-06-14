"""Structured note tracking for intake sessions."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from psychoanalyst_app.agents.intake.prompts import INTAKE_NOTE_TRACKING_PROMPT
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import IntakeRecord, IntakeRecordPatch
from psychoanalyst_app.services.llm_phases import INTAKE_NOTE_TRACKING

if TYPE_CHECKING:
    from psychoanalyst_app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


async def extract_intake_record_patch(
    *,
    llm_service: LLMService,
    current_record: IntakeRecord,
    latest_user_message: Message,
    previous_assistant_message: Message | None,
    source_message_index: int,
) -> IntakeRecordPatch | None:
    """Extract a structured patch from the latest patient message."""
    prompt = INTAKE_NOTE_TRACKING_PROMPT.format(
        current_record_json=json.dumps(
            current_record.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=True,
        ),
        previous_assistant_message=(
            previous_assistant_message.content if previous_assistant_message else ""
        ),
        latest_user_message=latest_user_message.content,
        source_message_index=source_message_index,
    )
    try:
        output = await llm_service.generate_structured_output_async(
            prompt,
            IntakeRecordPatch,
            method="json_schema",
            phase=INTAKE_NOTE_TRACKING,
        )
    except Exception:
        logger.warning("Intake note tracking failed", exc_info=True)
        return None

    if isinstance(output, IntakeRecordPatch):
        return output
    if isinstance(output, dict):
        try:
            return IntakeRecordPatch.model_validate(output)
        except Exception:
            logger.warning(
                "Intake note tracking returned malformed patch",
                exc_info=True,
            )
            return None

    logger.warning("Intake note tracking returned unexpected type: %s", type(output))
    return None
