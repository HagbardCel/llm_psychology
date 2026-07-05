"""Structured intake note patch extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import trio
from pydantic import ValidationError

from psychoanalyst_app.agents.intake.record_merge import count_patch_evidence
from psychoanalyst_app.agents.note_taker.intake_contract import (
    format_intake_note_tracking_prompt,
)
from psychoanalyst_app.exceptions import LLMServiceError
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
    "timeout",
]


@dataclass(frozen=True)
class IntakePatchExtractionResult:
    """Result of extracting a structured intake record patch."""

    status: IntakePatchExtractionStatus
    patch: IntakeRecordPatch | None = None
    error_message: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status == "success" and self.patch is None:
            raise ValueError("success extraction requires a patch")
        if self.status != "success" and self.patch is not None:
            raise ValueError("non-success extraction must not include a patch")
        if self.status in {"invalid_patch", "llm_failure", "timeout"} and not (
            self.error_message or self.error_code
        ):
            raise ValueError("failure extraction requires error diagnostics")


async def extract_intake_record_patch(
    *,
    llm_service: LLMService,
    current_record: IntakeRecord,
    latest_user_message: Message,
    previous_assistant_message: Message | None,
    source_message_index: int,
    timeout_seconds: float = 20.0,
) -> IntakePatchExtractionResult:
    """Extract a structured patch from the latest patient message."""
    prompt = format_intake_note_tracking_prompt(
        current_record=current_record,
        latest_user_message=latest_user_message.content,
        previous_assistant_message=(
            previous_assistant_message.content
            if previous_assistant_message is not None
            else None
        ),
        source_message_index=source_message_index,
    )
    try:
        with trio.fail_after(timeout_seconds):
            output = await llm_service.generate_structured_output_async(
                prompt,
                IntakeRecordPatch,
                method="json_schema",
                phase=INTAKE_NOTE_TRACKING,
                abandon_on_cancel=True,
            )
    except trio.TooSlowError:
        logger.warning("Intake note tracking timed out", exc_info=True)
        return IntakePatchExtractionResult(
            status="timeout",
            error_message="Intake note extraction timed out",
            error_code="timeout",
        )
    except trio.Cancelled:
        raise
    except Exception as exc:
        logger.warning("Intake note tracking failed", exc_info=True)
        error_message, error_code = _extraction_error_diagnostics(exc)
        return IntakePatchExtractionResult(
            status="llm_failure",
            error_message=error_message,
            error_code=error_code,
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

    if patch.no_new_information and count_patch_evidence(patch) > 0:
        return IntakePatchExtractionResult(
            status="invalid_patch",
            error_message="no_new_information=true with populated evidence",
            error_code="conflicting_no_new_information",
        )
    if patch.no_new_information:
        return IntakePatchExtractionResult(status="no_new_information")
    return IntakePatchExtractionResult(status="success", patch=patch)


def _extraction_error_diagnostics(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, LLMServiceError):
        metadata = exc.metadata or {}
        parts: list[str] = []
        for key in (
            "phase",
            "schema_name",
            "provider",
            "model_name",
            "parse_error_type",
            "parse_error",
        ):
            value = metadata.get(key)
            if value:
                parts.append(f"{key}={value}")
        return (
            "; ".join(parts) if parts else str(exc),
            type(exc).__name__,
        )
    return str(exc), type(exc).__name__
