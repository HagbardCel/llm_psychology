from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from psychoanalyst_app.models.domain import Message, Session
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    PresentingProblemRecord,
)
from psychoanalyst_app.orchestration.intake_turn_persistence import (
    build_intake_turn_diagnostics,
    extract_intake_turn_persistence_payload,
    mark_intake_record_persisted,
    persist_intake_turn_outputs,
)
from psychoanalyst_app.orchestration.models import AgentResponse, WorkflowState


def _record() -> IntakeRecord:
    return IntakeRecord(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="anxiety",
                evidence_quote="I feel anxious",
                source_message_index=1,
                source_role="user",
            )
        )
    )


def _response_with_intake(**extra_metadata) -> AgentResponse:
    metadata = {
        "intake_record": _record(),
        "intake_record_persistence": {"record_changed": True, "should_persist": True},
        "intake_note_tracking": {
            "status": "success",
            "merge_status": "applied",
            "applied": True,
            "raw_evidence_count": 1,
            "retained_evidence_count": 1,
            "dropped_evidence_count": 0,
            "drop_reasons": [],
            "drop_reasons_total": 0,
            "drop_reasons_truncated": False,
        },
    }
    metadata.update(extra_metadata)
    return AgentResponse(
        content="Hi",
        next_action="continue",
        next_state=WorkflowState.INTAKE_IN_PROGRESS,
        metadata=metadata,
    )


def _conversation_manager(session: Session) -> MagicMock:
    trio_db_service = AsyncMock()
    trio_db_service.get_session.return_value = session
    trio_db_service.save_session.return_value = True
    cm = MagicMock()
    cm.db_service = trio_db_service
    cm.active_contexts = {}
    return cm


@pytest.mark.trio
async def test_persist_intake_turn_outputs_writes_record_and_diagnostics():
    session = Session(
        session_id="s1",
        user_id="u1",
        timestamp=datetime.now(),
        transcript=[Message(role="user", content="hello", timestamp=datetime.now())],
    )
    cm = _conversation_manager(session)
    payload = extract_intake_turn_persistence_payload(_response_with_intake())

    persisted = await persist_intake_turn_outputs(cm, "s1", payload)

    assert persisted is True
    assert isinstance(session.intake_record, IntakeRecord)
    assert session.intake_record_updated_at is not None
    assert session.intake_note_tracking_diagnostics is not None
    assert session.intake_note_tracking_diagnostics["merge_status"] == "applied"
    cm.db_service.save_session.assert_awaited_once_with(session)


@pytest.mark.trio
async def test_persist_intake_turn_outputs_preserves_transcript():
    user_msg = Message(role="user", content="final coping answer", timestamp=datetime.now())
    session = Session(
        session_id="s1",
        user_id="u1",
        timestamp=datetime.now(),
        transcript=[user_msg],
    )
    cm = _conversation_manager(session)
    payload = extract_intake_turn_persistence_payload(_response_with_intake())

    await persist_intake_turn_outputs(cm, "s1", payload)

    assert session.transcript == [user_msg]
    assert session.transcript[0].content == "final coping answer"


@pytest.mark.trio
async def test_persist_intake_turn_outputs_persists_diagnostics_without_record():
    session = Session(
        session_id="s1",
        user_id="u1",
        timestamp=datetime.now(),
        transcript=[],
    )
    cm = _conversation_manager(session)
    response = AgentResponse(
        content="Hi",
        next_action="continue",
        metadata={
            "intake_note_tracking": {
                "status": "failure",
                "merge_status": "empty_after_validation",
                "applied": False,
                "raw_evidence_count": 1,
                "retained_evidence_count": 0,
                "dropped_evidence_count": 1,
                "drop_reasons": [
                    {"field_path": "coping.substances_or_medication", "reason": "quote_not_found_in_message"}
                ],
                "drop_reasons_total": 1,
                "drop_reasons_truncated": False,
                "error_code": None,
                "error_message": None,
            },
        },
    )
    payload = extract_intake_turn_persistence_payload(response)

    assert payload is not None
    assert payload.record is None
    assert payload.record_changed is False

    persisted = await persist_intake_turn_outputs(cm, "s1", payload)

    assert persisted is True
    assert session.intake_record is None
    assert session.intake_note_tracking_diagnostics["merge_status"] == "empty_after_validation"
    assert session.intake_note_tracking_diagnostics["drop_reasons"][0]["reason"] == (
        "quote_not_found_in_message"
    )


def test_mark_intake_record_persisted_sets_stage_and_timestamp():
    response = _response_with_intake()
    mark_intake_record_persisted(response, persisted_stage="pre_stream")

    persistence = response.metadata["intake_record_persistence"]
    assert persistence["persisted"] is True
    assert persistence["persisted_stage"] == "pre_stream"
    assert "persisted_at" in persistence
    # timezone-aware ISO string ends with +00:00
    assert persistence["persisted_at"].endswith("+00:00")


def test_build_intake_turn_diagnostics_compact_shape():
    tracking = {
        "status": "success",
        "raw_extraction_status": "success",
        "merge_status": "applied",
        "applied": True,
        "raw_evidence_count": 2,
        "retained_evidence_count": 1,
        "dropped_evidence_count": 1,
        "drop_reasons": [{"field_path": "coping.attempted_strategies[0]", "reason": "missing_value"}],
        "drop_reasons_total": 1,
        "drop_reasons_truncated": False,
    }
    diagnostics = build_intake_turn_diagnostics(tracking)
    assert diagnostics is not None
    assert diagnostics["retained_evidence_count"] == 1
    assert diagnostics["drop_reasons_total"] == 1
    assert diagnostics["drop_reasons"][0]["field_path"] == "coping.attempted_strategies[0]"
    # Must not include full record / transcript / prompt text
    assert "intake_record" not in diagnostics
    assert "prompt" not in diagnostics


def test_extract_payload_returns_none_when_no_intake_metadata():
    response = AgentResponse(content="Hi", next_action="continue", metadata={})
    assert extract_intake_turn_persistence_payload(response) is None
