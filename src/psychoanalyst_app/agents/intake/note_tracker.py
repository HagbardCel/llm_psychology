"""Structured note tracking for intake sessions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError

from psychoanalyst_app.agents.intake.prompts import INTAKE_NOTE_TRACKING_PROMPT
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import IntakeRecord, IntakeRecordPatch
from psychoanalyst_app.services.llm_phases import INTAKE_NOTE_TRACKING

if TYPE_CHECKING:
    from psychoanalyst_app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

IntakePatchExtractionStatus = Literal[
    "success",
    "no_new_information",
    "invalid_patch",
    "llm_failure",
]


@dataclass(frozen=True)
class IntakePatchExtractionResult:
    """Result of extracting a structured intake record patch."""

    status: IntakePatchExtractionStatus
    patch: IntakeRecordPatch | None = None
    error_message: str | None = None
    error_code: str | None = None


async def extract_intake_record_patch(
    *,
    llm_service: LLMService,
    current_record: IntakeRecord,
    latest_user_message: Message,
    previous_assistant_message: Message | None,
    source_message_index: int,
) -> IntakePatchExtractionResult:
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
    except Exception as exc:
        logger.warning("Intake note tracking failed", exc_info=True)
        return IntakePatchExtractionResult(
            status="llm_failure",
            error_message=str(exc),
            error_code=type(exc).__name__,
        )

    patch: IntakeRecordPatch
    if isinstance(output, IntakeRecordPatch):
        patch = output
    elif isinstance(output, dict):
        try:
            patch = IntakeRecordPatch.model_validate(output)
        except ValidationError as exc:
            logger.warning(
                "Intake note tracking returned malformed patch",
                exc_info=True,
            )
            return IntakePatchExtractionResult(
                status="invalid_patch",
                error_message=str(exc),
                error_code=type(exc).__name__,
            )
    else:
        logger.warning(
            "Intake note tracking returned unexpected type: %s",
            type(output),
        )
        return IntakePatchExtractionResult(
            status="invalid_patch",
            error_message=f"Unexpected output type: {type(output).__name__}",
            error_code="unexpected_output_type",
        )

    if patch.no_new_information:
        return IntakePatchExtractionResult(status="no_new_information")
    return IntakePatchExtractionResult(status="success", patch=patch)
