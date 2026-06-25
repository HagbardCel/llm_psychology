from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from psychoanalyst_app.agents.intake.note_tracker import extract_intake_record_patch
from psychoanalyst_app.agents.intake.note_tracking_contract import (
    format_intake_note_tracking_prompt,
)
from psychoanalyst_app.agents.intake.record_merge import (
    count_patch_evidence,
    merge_intake_record_patch_with_diagnostics,
)
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import IntakeRecord, IntakeRecordPatch
from psychoanalyst_app.testing.fakes import DeterministicLLMService
from psychoanalyst_app.testing.intake_fake_extraction import (
    build_fake_intake_patch_payload,
    parse_prompt_anchors,
)

pytestmark = [pytest.mark.unit]

SMOKE_REPLIES = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "console-ui/scenarios/workflow-probes/first_session_smoke.json"
    ).read_text(encoding="utf-8")
)["deterministic_chat_replies"]


def _note_tracking_prompt(
    *,
    latest_user_message: str,
    source_message_index: int,
    previous_assistant_message: str | None = None,
) -> str:
    return format_intake_note_tracking_prompt(
        current_record=IntakeRecord(),
        latest_user_message=latest_user_message,
        previous_assistant_message=previous_assistant_message,
        source_message_index=source_message_index,
    )


def _patch_from_prompt(prompt: str) -> IntakeRecordPatch:
    payload = build_fake_intake_patch_payload(prompt)
    return IntakeRecordPatch.model_validate(payload)


def _user_message(content: str) -> Message:
    return Message(role="user", content=content, timestamp=datetime.now())


def test_parse_prompt_anchors_extracts_optional_previous_message() -> None:
    prompt = _note_tracking_prompt(
        latest_user_message="I feel anxious",
        source_message_index=4,
        previous_assistant_message="How long has this been going on?",
    )

    parsed = parse_prompt_anchors(prompt)

    assert parsed.is_valid is True
    assert parsed.latest_user_message == "I feel anxious"
    assert parsed.source_message_index == 4
    assert parsed.previous_therapist_message == "How long has this been going on?"


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("LATEST PATIENT MESSAGE:\n\nSOURCE MESSAGE INDEX:\n1", False),
        ("LATEST PATIENT MESSAGE:\nhello\nSOURCE MESSAGE INDEX:\nabc", False),
        ("no anchors here", False),
    ],
)
def test_parse_prompt_anchors_invalid_cases(prompt: str, expected: bool) -> None:
    assert parse_prompt_anchors(prompt).is_valid is expected


@pytest.mark.parametrize(
    ("message", "checker"),
    [
        (
            "I struggle with procrastination and anxiety",
            lambda patch: patch.presenting_problem is not None
            and patch.presenting_problem.main_concern.value is not None,
        ),
        (
            "This has been going on for years",
            lambda patch: patch.presenting_problem is not None
            and patch.presenting_problem.time_course.duration_or_onset.value
            is not None,
        ),
        (
            "I want more confidence",
            lambda patch: patch.goals is not None
            and bool(patch.goals.therapy_goals),
        ),
        (
            "I avoid letters and admin tasks",
            lambda patch: patch.presenting_problem is not None
            and patch.presenting_problem.functional_impairment.value is not None,
        ),
        (
            "I usually distract myself",
            lambda patch: patch.coping is not None
            and bool(patch.coping.attempted_strategies),
        ),
        (
            (
                "I have not had thoughts of harming myself or anyone else. "
                "The chest tightness is not medically urgent."
            ),
            lambda patch: patch.safety is not None
            and patch.safety.self_harm.value == "none reported"
            and patch.safety.harm_to_others.value == "none reported"
            and patch.safety.medical_urgency.value == "none reported",
        ),
        (
            "Thanks, that makes sense",
            lambda patch: patch.no_new_information is True,
        ),
    ],
)
def test_fake_extraction_per_field_cases(message: str, checker) -> None:
    patch = _patch_from_prompt(
        _note_tracking_prompt(latest_user_message=message, source_message_index=3)
    )
    assert checker(patch)


def test_fake_extraction_unknown_routes_to_duration_by_default() -> None:
    patch = _patch_from_prompt(
        _note_tracking_prompt(
            latest_user_message="I don't know",
            source_message_index=5,
            previous_assistant_message=None,
        )
    )

    duration = patch.presenting_problem.time_course.duration_or_onset
    assert duration.response_status == "unknown"
    assert duration.direct_ask is True
    assert duration.value is None


def test_fake_extraction_unable_to_answer_marks_all_safety_fields() -> None:
    patch = _patch_from_prompt(
        _note_tracking_prompt(
            latest_user_message="I don't want to answer that",
            source_message_index=6,
            previous_assistant_message=(
                "Have you had thoughts of harming yourself or someone else?"
            ),
        )
    )

    assert patch.safety is not None
    assert patch.safety.self_harm.response_status == "unable_to_answer"
    assert patch.safety.harm_to_others.response_status == "unable_to_answer"
    assert patch.safety.medical_urgency.response_status == "unable_to_answer"
    assert patch.safety.self_harm.direct_ask is True


def test_routing_precedence_unknown_over_goals() -> None:
    patch = _patch_from_prompt(
        _note_tracking_prompt(
            latest_user_message="I don't know, I just want to feel better",
            source_message_index=7,
            previous_assistant_message="How long has this been going on?",
        )
    )

    duration = patch.presenting_problem.time_course.duration_or_onset
    assert duration.response_status == "unknown"
    assert patch.goals is None


def test_routing_precedence_functional_impairment_over_goals() -> None:
    patch = _patch_from_prompt(
        _note_tracking_prompt(
            latest_user_message="I want to avoid people at work",
            source_message_index=8,
        )
    )

    assert patch.presenting_problem is not None
    assert patch.presenting_problem.functional_impairment.value is not None
    assert patch.goals is None


def test_safety_precision_avoid_others_is_not_harm_to_others() -> None:
    patch = _patch_from_prompt(
        _note_tracking_prompt(
            latest_user_message="I avoid others when anxious",
            source_message_index=9,
        )
    )

    assert patch.safety is None


def test_no_new_information_conflict_invariant() -> None:
    cases = [
        "Thanks, that makes sense",
        "no anchors",
        "",
    ]
    for message in cases:
        prompt = (
            _note_tracking_prompt(latest_user_message=message, source_message_index=1)
            if message not in {"no anchors", ""}
            else message
        )
        patch = _patch_from_prompt(prompt)
        if patch.no_new_information:
            assert count_patch_evidence(patch) == 0


def test_informative_evidence_validity_invariant() -> None:
    message = "I have been anxious about work for three months."
    index = 11
    patch = _patch_from_prompt(
        _note_tracking_prompt(latest_user_message=message, source_message_index=index)
    )
    evidence = patch.presenting_problem.time_course.duration_or_onset

    assert evidence.source_role == "user"
    assert evidence.source_message_index == index
    assert evidence.evidence_quote == message


@pytest.mark.trio
async def test_end_to_end_deterministic_extraction_merge_applies_evidence() -> None:
    llm = DeterministicLLMService()
    message = "I struggle with procrastination and anxiety"
    user_message = _user_message(message)

    result = await extract_intake_record_patch(
        llm_service=llm,
        current_record=IntakeRecord(),
        latest_user_message=user_message,
        previous_assistant_message=None,
        source_message_index=3,
    )

    assert result.status == "success"
    assert result.patch is not None
    merge = merge_intake_record_patch_with_diagnostics(
        IntakeRecord(),
        result.patch,
        latest_user_message=user_message,
        source_message_index=3,
        strict_quote_validation=True,
    )
    assert merge.status == "applied"
    assert merge.record.presenting_problem.main_concern.is_present()


def test_first_session_smoke_replies_progressively_populate_record() -> None:
    record = IntakeRecord()
    for index, reply in enumerate(SMOKE_REPLIES, start=1):
        patch = _patch_from_prompt(
            _note_tracking_prompt(latest_user_message=reply, source_message_index=index)
        )
        merge = merge_intake_record_patch_with_diagnostics(
            record,
            patch,
            latest_user_message=_user_message(reply),
            source_message_index=index,
            strict_quote_validation=True,
        )
        if merge.applied:
            record = merge.record

    assert record.presenting_problem.main_concern.is_present()
    assert record.presenting_problem.time_course.duration_or_onset.is_present()
    assert record.safety.is_addressed()
    assert record.presenting_problem.functional_impairment.is_present()
    assert record.goals is not None
    assert any(goal.is_present() for goal in record.goals.therapy_goals)
    assert record.coping is not None
    assert any(
        strategy.is_present() for strategy in record.coping.attempted_strategies
    )


def test_targets_for_previous_message_constants_are_used_for_safety() -> None:
    patch = _patch_from_prompt(
        _note_tracking_prompt(
            latest_user_message="I don't know",
            source_message_index=2,
            previous_assistant_message="Any safety or urgent risk concerns?",
        )
    )

    assert patch.safety is not None
    assert patch.safety.self_harm.response_status == "unknown"
    assert patch.safety.harm_to_others.response_status == "unknown"
    assert patch.safety.medical_urgency.response_status == "unknown"


@pytest.mark.parametrize(
    ("message", "expect_sleep_impact", "expect_goals"),
    [
        ("I want to sleep better.", False, True),
        ("I have been sleeping badly.", True, False),
        ("I keep waking up at night.", True, False),
        ("I have trouble sleeping and lie awake for hours.", True, False),
        ("My goal is to sleep better because I wake up at night.", False, True),
    ],
)
def test_sleep_impact_matcher_routing(
    message: str, expect_sleep_impact: bool, expect_goals: bool
) -> None:
    patch = _patch_from_prompt(
        _note_tracking_prompt(latest_user_message=message, source_message_index=4)
    )

    if expect_sleep_impact:
        assert patch.presenting_problem is not None
        assert patch.presenting_problem.sleep_impact.value is not None
        assert patch.goals is None
    if expect_goals:
        assert patch.goals is not None
        assert bool(patch.goals.therapy_goals)


def test_sleep_impact_evidence_carries_user_source() -> None:
    message = "I have been sleeping badly and waking up at night."
    index = 12
    patch = _patch_from_prompt(
        _note_tracking_prompt(latest_user_message=message, source_message_index=index)
    )

    evidence = patch.presenting_problem.sleep_impact
    assert evidence.source_role == "user"
    assert evidence.source_message_index == index
    assert evidence.evidence_quote == message


def test_sleep_impact_disclosure_completes_soft_items() -> None:
    record = IntakeRecord()
    merge = merge_intake_record_patch_with_diagnostics(
        record,
        _patch_from_prompt(
            _note_tracking_prompt(
                latest_user_message="I have been sleeping badly and waking up at night.",
                source_message_index=7,
            )
        ),
        latest_user_message=_user_message(
            "I have been sleeping badly and waking up at night."
        ),
        source_message_index=7,
        strict_quote_validation=True,
    )
    assert merge.applied
    assert merge.record.presenting_problem.sleep_impact.is_present()
