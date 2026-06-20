from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from psychoanalyst_app.agents.intake.note_tracking_contract import (
    FIELD_GUIDANCE_BY_PATH,
    FORBIDDEN_PROMPT_FIELD_NAMES,
    INFORMATIVE_EXAMPLE_NAMES,
    NOTE_TRACKING_PROMPT_EXAMPLES,
    format_intake_note_tracking_prompt,
    intake_evidence_fields,
    intake_evidence_required_for_informative,
    intake_patch_evidence_paths,
    intake_patch_top_level_fields,
    render_patch_shape_block,
)
from psychoanalyst_app.agents.intake.record_merge import merge_intake_record_patch
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import IntakeRecord, IntakeRecordPatch

pytestmark = pytest.mark.unit


def _rendered_prompt(
    *,
    current_record: IntakeRecord | None = None,
    latest_user_message: str = "I feel anxious every day.",
    previous_assistant_message: str | None = None,
    source_message_index: int = 2,
) -> str:
    return format_intake_note_tracking_prompt(
        current_record=current_record or IntakeRecord(),
        latest_user_message=latest_user_message,
        previous_assistant_message=previous_assistant_message,
        source_message_index=source_message_index,
    )


def get_path(obj: dict[str, Any], dotted_path: str) -> Any:
    current: Any = obj
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _evidence_leaves_populated(patch: dict[str, Any]) -> list[str]:
    populated: list[str] = []
    for path in intake_patch_evidence_paths():
        value = get_path(patch, path)
        if value is None:
            continue
        if isinstance(value, list):
            if value:
                populated.append(path)
            continue
        if isinstance(value, dict) and (
            value.get("value") or value.get("evidence_quote")
        ):
            populated.append(path)
    return populated


def test_inventory_walker_covers_known_paths() -> None:
    paths = set(intake_patch_evidence_paths())
    assert "presenting_problem.main_concern" in paths
    assert "presenting_problem.time_course.duration_or_onset" in paths
    assert "safety.self_harm" in paths
    assert "coping.attempted_strategies" in paths
    assert "goals.therapy_goals" in paths


def test_rendered_prompt_mentions_all_top_level_patch_fields() -> None:
    prompt = _rendered_prompt()
    for field_name in intake_patch_top_level_fields():
        assert field_name in prompt


def test_rendered_prompt_mentions_all_evidence_paths() -> None:
    prompt = _rendered_prompt()
    for path in intake_patch_evidence_paths():
        assert path in prompt


def test_rendered_prompt_mentions_evidence_object_fields() -> None:
    prompt = _rendered_prompt()
    for field_name in intake_evidence_fields():
        assert field_name in prompt
    for field_name in intake_evidence_required_for_informative():
        assert field_name in prompt


def test_format_replaces_runtime_slots() -> None:
    prompt = _rendered_prompt(
        latest_user_message="Latest patient text here.",
        previous_assistant_message=None,
        source_message_index=7,
    )
    assert "Latest patient text here." in prompt
    assert "7" in prompt
    assert "{current_record_json}" not in prompt
    assert "{latest_user_message}" not in prompt
    assert "{source_message_index}" not in prompt
    assert "{patch_shape}" not in prompt
    assert "{examples}" not in prompt
    assert "{field_guidance}" not in prompt
    assert "None" not in prompt.split("PREVIOUS THERAPIST MESSAGE:")[1].split(
        "LATEST PATIENT MESSAGE:"
    )[0]


def test_format_prompt_does_not_raise_with_json_like_inputs() -> None:
    prompt = _rendered_prompt(
        latest_user_message='I wrote {"foo": "bar"} in my notes.',
    )
    assert '{"foo": "bar"}' in prompt


def test_prompt_examples_are_rendered() -> None:
    prompt = _rendered_prompt()
    for example in NOTE_TRACKING_PROMPT_EXAMPLES:
        assert f"Example: {example.name}" in prompt
        assert example.user_message in prompt


def test_prompt_examples_validate_against_schema() -> None:
    for example in NOTE_TRACKING_PROMPT_EXAMPLES:
        IntakeRecordPatch.model_validate(example.patch)


def test_prompt_examples_merge_successfully() -> None:
    for example in NOTE_TRACKING_PROMPT_EXAMPLES:
        patch = IntakeRecordPatch.model_validate(example.patch)
        merge_intake_record_patch(
            IntakeRecord(),
            patch,
            latest_user_message=Message(
                role="user",
                content=example.user_message,
                timestamp=datetime.now(),
            ),
            source_message_index=example.source_message_index,
            strict_quote_validation=True,
        )


def test_informative_examples_pass_strict_merge_validation() -> None:
    for example in NOTE_TRACKING_PROMPT_EXAMPLES:
        if example.name not in INFORMATIVE_EXAMPLE_NAMES:
            continue
        patch = IntakeRecordPatch.model_validate(example.patch)
        merged = merge_intake_record_patch(
            IntakeRecord(),
            patch,
            latest_user_message=Message(
                role="user",
                content=example.user_message,
                timestamp=datetime.now(),
            ),
            source_message_index=example.source_message_index,
            strict_quote_validation=True,
        )
        assert merged != IntakeRecord()


def _find_evidence_with_status(
    patch: Any,
    statuses: set[str],
) -> dict[str, Any] | None:
    if isinstance(patch, dict):
        if patch.get("response_status") in statuses:
            return patch
        for value in patch.values():
            found = _find_evidence_with_status(value, statuses)
            if found is not None:
                return found
    elif isinstance(patch, list):
        for item in patch:
            found = _find_evidence_with_status(item, statuses)
            if found is not None:
                return found
    return None


def test_unknown_and_unable_examples_have_direct_ask_true() -> None:
    for name in ("unknown", "unable_to_answer"):
        example = next(item for item in NOTE_TRACKING_PROMPT_EXAMPLES if item.name == name)
        evidence = _find_evidence_with_status(
            example.patch,
            {"unknown", "unable_to_answer"},
        )
        assert evidence is not None
        assert evidence["direct_ask"] is True
        assert evidence["response_status"] in {"unknown", "unable_to_answer"}


def test_unknown_and_unable_examples_have_previous_assistant_question() -> None:
    for name in ("unknown", "unable_to_answer"):
        example = next(item for item in NOTE_TRACKING_PROMPT_EXAMPLES if item.name == name)
        assert example.previous_assistant_message
        assert "?" in example.previous_assistant_message


def test_no_new_information_example_has_no_populated_evidence() -> None:
    example = next(
        item for item in NOTE_TRACKING_PROMPT_EXAMPLES if item.name == "no_new_information"
    )
    assert example.patch.get("no_new_information") is True
    assert _evidence_leaves_populated(example.patch) == []


def test_prompt_does_not_reference_forbidden_field_names() -> None:
    prompt = _rendered_prompt()
    for forbidden in FORBIDDEN_PROMPT_FIELD_NAMES:
        assert forbidden not in prompt


def test_field_guidance_covers_semantic_paths() -> None:
    prompt = _rendered_prompt()
    for path in FIELD_GUIDANCE_BY_PATH:
        assert path in prompt


def test_field_guidance_keys_are_valid_evidence_paths() -> None:
    valid_paths = set(intake_patch_evidence_paths())
    assert set(FIELD_GUIDANCE_BY_PATH) <= valid_paths


def test_list_evidence_paths_use_stable_representation() -> None:
    shape = render_patch_shape_block()
    list_paths = [
        path
        for path in intake_patch_evidence_paths()
        if path.endswith(
            (
                "symptoms",
                "triggers",
                "attempted_strategies",
                "therapy_goals",
            )
        )
        or "time_course.triggers" in path
    ]
    assert list_paths
    for path in list_paths:
        assert "[]" not in path
        assert f"{path}: list[IntakeEvidence]" in shape
