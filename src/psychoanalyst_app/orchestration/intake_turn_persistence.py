"""Pre-stream persistence of per-turn intake record + note-tracking diagnostics.

The intake patch is computed in ``agent.process_message`` and historically only
persisted during ``finalize_agent_response`` (after the assistant response
streams). A hung provider stream could therefore lose a successfully computed
patch. These helpers persist the intake record and compact per-turn
note-tracking diagnostics immediately after ``process_message`` and before
streaming, and mark the response so finalization does not duplicate the write.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from psychoanalyst_app.models.intake_record import IntakeRecord
from psychoanalyst_app.orchestration.models import AgentResponse

logger = logging.getLogger(__name__)

_PERSISTENCE_KEY = "intake_record_persistence"
_TRACKING_KEY = "intake_note_tracking"


@dataclass(frozen=True)
class IntakeTurnPersistencePayload:
    """Compact per-turn intake outputs to persist before streaming.

    ``record`` may be ``None`` when the turn produced diagnostics but no
    parseable record (e.g. a failed/invalid patch). In that case only the
    diagnostics are persisted with ``record_changed=False``.
    """

    record: IntakeRecord | None
    record_changed: bool
    diagnostics: dict[str, Any] | None


def build_intake_turn_diagnostics(
    tracking_metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a compact diagnostics object from note-tracking metadata.

    Deliberately excludes the full intake record, prompt text, and transcript
    fragments. Only bounded merge/drop metadata is retained.
    """
    if not tracking_metadata:
        return None
    drop_reasons = list(tracking_metadata.get("drop_reasons") or [])
    return {
        "status": tracking_metadata.get("status"),
        "raw_extraction_status": tracking_metadata.get("raw_extraction_status"),
        "merge_status": tracking_metadata.get("merge_status"),
        "applied": bool(tracking_metadata.get("applied", False)),
        "raw_evidence_count": int(tracking_metadata.get("raw_evidence_count", 0) or 0),
        "retained_evidence_count": int(
            tracking_metadata.get("retained_evidence_count", 0) or 0
        ),
        "dropped_evidence_count": int(
            tracking_metadata.get("dropped_evidence_count", 0) or 0
        ),
        "drop_reasons": drop_reasons,
        "drop_reasons_total": int(
            tracking_metadata.get("drop_reasons_total", len(drop_reasons)) or 0
        ),
        "drop_reasons_truncated": bool(
            tracking_metadata.get("drop_reasons_truncated", False)
        ),
        "error_code": tracking_metadata.get("error_code")
        or tracking_metadata.get("merge_error_code"),
        "error_message": tracking_metadata.get("error_message")
        or tracking_metadata.get("merge_error_message"),
    }


def _parse_intake_record(value: Any) -> IntakeRecord | None:
    if isinstance(value, IntakeRecord):
        return value
    if isinstance(value, dict):
        try:
            return IntakeRecord.model_validate(value)
        except ValidationError:
            logger.warning(
                "Invalid intake_record metadata payload", exc_info=True
            )
            return None
    if value is not None:
        logger.warning(
            "Ignoring unexpected intake_record payload type: %s", type(value)
        )
    return None


def extract_intake_turn_persistence_payload(
    agent_response: AgentResponse,
) -> IntakeTurnPersistencePayload | None:
    """Extract the per-turn intake outputs to persist, or ``None`` if absent.

    Diagnostics are persisted even when the record is absent/unparseable so a
    failed note-tracking turn remains diagnosable.
    """
    metadata = agent_response.metadata or {}
    if "intake_record" not in metadata and _TRACKING_KEY not in metadata:
        return None
    record = _parse_intake_record(metadata.get("intake_record"))
    tracking = metadata.get(_TRACKING_KEY)
    diagnostics = build_intake_turn_diagnostics(
        tracking if isinstance(tracking, dict) else None
    )
    persistence = metadata.get(_PERSISTENCE_KEY)
    record_changed = bool(
        persistence.get("record_changed")
        if isinstance(persistence, dict)
        else (record is not None)
    )
    if record is None and not diagnostics:
        return None
    return IntakeTurnPersistencePayload(
        record=record,
        record_changed=record_changed,
        diagnostics=diagnostics,
    )


def mark_intake_record_persisted(
    agent_response: AgentResponse,
    *,
    persisted_stage: str,
) -> None:
    """Mark the response metadata so finalization skips the intake write."""
    metadata = agent_response.metadata
    if metadata is None:
        return
    persistence = metadata.setdefault(_PERSISTENCE_KEY, {})
    if isinstance(persistence, dict):
        persistence["persisted"] = True
        persistence["persisted_stage"] = persisted_stage
        persistence["persisted_at"] = datetime.now(UTC).isoformat()


async def persist_intake_turn_outputs(
    conversation_manager,
    session_id: str,
    payload: IntakeTurnPersistencePayload,
) -> bool:
    """Persist intake record and/or diagnostics in a single fresh session write.

    Loads the session fresh from the DB (after the user message was recorded),
    modifies only the intake fields, and saves once so the latest transcript is
    preserved.
    """
    if payload.record is None and payload.diagnostics is None:
        return False
    updated_at = datetime.now()
    session = await conversation_manager.db_service.get_session(session_id)
    if session is None:
        logger.warning(
            "Session not found for intake turn persistence: %s", session_id
        )
        return False

    changed = False
    if payload.record is not None and payload.record_changed:
        session.intake_record = payload.record
        session.intake_record_updated_at = updated_at
        changed = True
    if payload.diagnostics is not None:
        session.intake_note_tracking_diagnostics = payload.diagnostics
        changed = True

    if not changed:
        return False

    saved = await conversation_manager.db_service.save_session(session)
    if not saved:
        logger.warning(
            "Did not persist intake turn outputs for session %s "
            "(immutable/enriched)",
            session_id,
        )
        return False

    if (
        session_id in conversation_manager.active_contexts
        and payload.record is not None
    ):
        context = conversation_manager.active_contexts[session_id]
        if payload.record_changed:
            context.intake_record = payload.record
            context.intake_record_updated_at = updated_at

    return True
