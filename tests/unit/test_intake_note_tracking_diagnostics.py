from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

from psychoanalyst_app.agents.intake.record_merge import (
    merge_intake_record_patch_with_diagnostics,
)
from psychoanalyst_app.agents.note_taker.intake_contract import (
    format_intake_note_tracking_prompt,
)
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
)
from psychoanalyst_app.testing.intake_fake_extraction import (
    build_fake_intake_patch_payload,
)

pytestmark = [pytest.mark.unit]


@pytest.fixture
def note_tracking_module(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repo_root / "src"))
    monkeypatch.syspath_prepend(str(repo_root / "console-ui"))
    module = importlib.import_module("src.workflow_probe.intake_note_tracking")
    yield module
    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            sys.modules.pop(name, None)


def _evidence_quote(message: str, index: int) -> IntakeEvidence:
    return IntakeEvidence(
        value="reported detail",
        evidence_quote=message,
        source_message_index=index,
        source_role="user",
        response_status="informative",
    )


def _build_complete_record() -> tuple[IntakeRecord, list[dict]]:
    """Merge a full-coverage deterministic transcript into a typed record."""
    replies = [
        "I struggle with anxiety about work.",
        "This has been going on for three months.",
        "I have not had thoughts of harming myself or anyone else. The chest tightness is not medically urgent.",
        "I tried breathing exercises when Monday deadlines make my chest tight.",
        "I want to sleep better and feel less anxious about Monday deadlines.",
        "I freeze when my manager pressures me about Monday deadlines and my chest tightens.",
        "I have been sleeping badly and keep waking up at night.",
    ]
    transcript = [{"role": "user", "content": reply} for reply in replies]
    record = IntakeRecord()
    for index, reply in enumerate(replies, start=1):
        prompt = format_intake_note_tracking_prompt(
            current_record=record,
            latest_user_message=reply,
            previous_assistant_message=None,
            source_message_index=index,
        )
        patch = IntakeRecordPatch.model_validate(build_fake_intake_patch_payload(prompt))
        merge = merge_intake_record_patch_with_diagnostics(
            record,
            patch,
            latest_user_message=Message(role="user", content=reply, timestamp=datetime.now()),
            source_message_index=index,
            strict_quote_validation=True,
        )
        if merge.applied:
            record = merge.record
    return record, transcript


def _row(record: IntakeRecord, *, session_id: str = "s-intake", ended: bool = True) -> dict:
    return {
        "session_id": session_id,
        "session_type": "intake",
        "timestamp": "2026-06-25T10:00:00Z",
        "ended_at": "2026-06-25T10:30:00Z" if ended else None,
        "intake_record": json.dumps(record.model_dump(mode="json")),
        "intake_record_updated_at": "2026-06-25T10:29:00Z",
    }


def _scenario(expected: bool = True, **overrides) -> dict:
    base = {
        "expected": expected,
        "require_structured_completion": True,
        "require_canonical_completion_source": True,
        "require_informative_goal": True,
    }
    base.update(overrides)
    return {"intake_note_tracking": base}


def test_diagnostics_complete_record_canonical(note_tracking_module):
    record, transcript = _build_complete_record()
    diagnostics = note_tracking_module.build_intake_note_tracking_diagnostics(
        [_row(record)], transcript, _scenario(), final_workflow_state="plan_update_complete"
    )

    assert diagnostics["session_found"] is True
    assert diagnostics["intake_record_persisted"] is True
    assert diagnostics["intake_record_parseable"] is True
    assert diagnostics["completion"]["source"] == "intake_record_completion_decision"
    assert diagnostics["completion"]["complete"] is True
    assert diagnostics["completion"]["missing_hard_items"] == []
    assert diagnostics["completion"]["missing_soft_items"] == []
    assert diagnostics["advanced_past_intake_in_progress"] is True
    assert diagnostics["failure_reasons"] == []
    items = diagnostics["items"]
    for key in (
        "presenting_problem",
        "duration",
        "risk_screen",
        "functional_impairment",
        "goal_preference",
        "coping_attempts",
        "sleep_impact",
    ):
        assert items[key]["present"] is True, key
        assert items[key]["has_valid_user_sourced_evidence"] is True, key


def test_diagnostics_missing_session(note_tracking_module):
    diagnostics = note_tracking_module.build_intake_note_tracking_diagnostics(
        [], [], _scenario(), final_workflow_state=None
    )
    assert diagnostics["session_found"] is False
    assert diagnostics["intake_record_persisted"] is False
    assert "intake_record not persisted" in diagnostics["failure_reasons"]


def test_diagnostics_multiple_candidate_sessions_flagged(note_tracking_module):
    record, transcript = _build_complete_record()
    rows = [_row(record, session_id="s1"), _row(record, session_id="s2")]
    diagnostics = note_tracking_module.build_intake_note_tracking_diagnostics(
        rows, transcript, _scenario(), final_workflow_state="plan_update_complete"
    )
    assert diagnostics["candidate_session_count"] == 2
    assert any("multiple candidate" in reason for reason in diagnostics["failure_reasons"])


def test_diagnostics_unparseable_record(note_tracking_module):
    rows = [
        {
            "session_id": "s-bad",
            "session_type": "intake",
            "timestamp": "2026-06-25T10:00:00Z",
            "ended_at": "2026-06-25T10:30:00Z",
            "intake_record": "{not json",
            "intake_record_updated_at": "2026-06-25T10:29:00Z",
        }
    ]
    diagnostics = note_tracking_module.build_intake_note_tracking_diagnostics(
        rows, [], _scenario(), final_workflow_state="plan_update_complete"
    )
    assert diagnostics["intake_record_persisted"] is True
    assert diagnostics["intake_record_parseable"] is False
    assert "intake_record present but not parseable" in diagnostics["failure_reasons"]


def test_diagnostics_incomplete_record_reports_missing(note_tracking_module):
    record = IntakeRecord()
    record.presenting_problem.main_concern = _evidence_quote("I feel anxious", 1)
    diagnostics = note_tracking_module.build_intake_note_tracking_diagnostics(
        [_row(record)], [{"role": "user", "content": "I feel anxious"}],
        _scenario(),
        final_workflow_state="intake_in_progress",
    )
    assert diagnostics["completion"]["complete"] is False
    assert "structured completion not reached" in diagnostics["failure_reasons"]
    assert diagnostics["advanced_past_intake_in_progress"] is False


def test_diagnostics_evidence_integrity_detects_missing_user_source(note_tracking_module):
    record = IntakeRecord()
    # Present but lacking user source / quote -> not valid user evidence.
    record.presenting_problem.main_concern = IntakeEvidence(
        value="anxiety", evidence_quote=None, source_message_index=None, source_role=None
    )
    diagnostics = note_tracking_module.build_intake_note_tracking_diagnostics(
        [_row(record)], [{"role": "user", "content": "x"}], _scenario(),
        final_workflow_state="plan_update_complete",
    )
    item = diagnostics["items"]["presenting_problem"]
    assert item["has_valid_user_sourced_evidence"] is False


def test_diagnostics_structural_fallback_when_canonical_unavailable(
    note_tracking_module, monkeypatch
):
    record, transcript = _build_complete_record()
    monkeypatch.setattr(note_tracking_module, "_CANONICAL_COMPLETION_AVAILABLE", False)
    monkeypatch.setattr(note_tracking_module, "intake_record_completion_decision", None)
    diagnostics = note_tracking_module.build_intake_note_tracking_diagnostics(
        [_row(record)], transcript, _scenario(), final_workflow_state="plan_update_complete"
    )
    assert diagnostics["completion"]["source"] == "structural_fallback"
    assert any(
        "structural fallback" in reason for reason in diagnostics["failure_reasons"]
    )


def test_diagnostics_goal_marked_unknown_does_not_satisfy_informative_goal(
    note_tracking_module,
):
    record, transcript = _build_complete_record()
    record = record.model_copy(deep=True)
    record.goals.therapy_goals = [
        IntakeEvidence(
            value=None,
            evidence_quote="I don't know",
            source_message_index=5,
            source_role="user",
            response_status="unknown",
            direct_ask=True,
        )
    ]
    diagnostics = note_tracking_module.build_intake_note_tracking_diagnostics(
        [_row(record)], transcript, _scenario(), final_workflow_state="plan_update_complete"
    )
    assert diagnostics["items"]["goal_preference"]["present"] is False
    assert "goal_preference not informatively present" in diagnostics["failure_reasons"]


def test_diagnostics_expected_false_returns_no_expectations(note_tracking_module):
    record, transcript = _build_complete_record()
    diagnostics = note_tracking_module.build_intake_note_tracking_diagnostics(
        [_row(record)], transcript, _scenario(expected=False), final_workflow_state=None
    )
    assert diagnostics["expected"] is False
    # No expectation-driven failure reasons.
    assert not any("not persisted" in r for r in diagnostics["failure_reasons"])


def test_diagnostics_dict_fallback_path_without_typed_model(note_tracking_module, monkeypatch):
    record, transcript = _build_complete_record()
    monkeypatch.setattr(note_tracking_module, "_INTAKE_RECORD_AVAILABLE", False)
    monkeypatch.setattr(note_tracking_module, "IntakeRecord", None)
    monkeypatch.setattr(note_tracking_module, "_CANONICAL_COMPLETION_AVAILABLE", False)
    monkeypatch.setattr(note_tracking_module, "intake_record_completion_decision", None)
    diagnostics = note_tracking_module.build_intake_note_tracking_diagnostics(
        [_row(record)], transcript, _scenario(), final_workflow_state="plan_update_complete"
    )
    assert diagnostics["intake_record_parseable"] is True
    assert diagnostics["completion"]["source"] == "structural_fallback"
    items = diagnostics["items"]
    for key in (
        "presenting_problem",
        "duration",
        "risk_screen",
        "functional_impairment",
        "goal_preference",
        "coping_attempts",
        "sleep_impact",
    ):
        assert items[key]["present"] is True, key
        assert items[key]["has_valid_user_sourced_evidence"] is True, key
    assert any(
        "structural fallback" in reason for reason in diagnostics["failure_reasons"]
    )
