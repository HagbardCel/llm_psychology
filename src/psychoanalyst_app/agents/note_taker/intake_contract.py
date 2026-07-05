"""Prompt contract helpers for structured intake note tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

from psychoanalyst_app.agents.intake.prompts import INTAKE_NOTE_TRACKING_PROMPT
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
)

FORBIDDEN_PROMPT_FIELD_NAMES = frozenset({"current_blockers", "relevant_context"})

INFORMATIVE_EXAMPLE_NAMES = frozenset(
    {
        "presenting_problem",
        "duration",
        "goals",
        "functional_impairment",
        "coping",
        "safety_negative",
    }
)

FIELD_GUIDANCE_BY_PATH: dict[str, str] = {
    "presenting_problem.time_course.duration_or_onset": (
        "How long or since when (e.g. for three months, since childhood)."
    ),
    "presenting_problem.time_course.frequency": (
        "How often (e.g. daily, twice a week). Not the same as duration_or_onset."
    ),
    "presenting_problem.time_course.triggers": (
        "Situations that cause or worsen the issue. A trigger alone is not duration."
    ),
    "presenting_problem.functional_impairment": (
        "Work, social, or day-to-day impact (avoidance, impairment, blockers)."
    ),
    "coping.attempted_strategies": "What the patient has tried to cope.",
    "coping.substances_or_medication": "Substances or medication used to cope.",
    "goals.therapy_goals": "What the patient wants from therapy.",
    "goals.preferred_start": "When or how they want to begin.",
    "safety.self_harm": "Thoughts of self-harm; include explicit denials.",
    "safety.harm_to_others": "Thoughts of harming others; include explicit denials.",
    "safety.medical_urgency": "Urgent medical or psychiatric safety concerns.",
}


@dataclass(frozen=True)
class PromptExample:
    name: str
    user_message: str
    source_message_index: int
    previous_assistant_message: str | None
    patch: dict[str, Any]


NOTE_TRACKING_PROMPT_EXAMPLES: tuple[PromptExample, ...] = (
    PromptExample(
        name="presenting_problem",
        user_message="I struggle with procrastination and anxiety",
        source_message_index=3,
        previous_assistant_message=None,
        patch={
            "presenting_problem": {
                "main_concern": {
                    "value": "procrastination and anxiety",
                    "evidence_quote": "I struggle with procrastination and anxiety",
                    "source_role": "user",
                    "source_message_index": 3,
                }
            }
        },
    ),
    PromptExample(
        name="duration",
        user_message="This has been going on for years",
        source_message_index=4,
        previous_assistant_message=None,
        patch={
            "presenting_problem": {
                "time_course": {
                    "duration_or_onset": {
                        "value": "years",
                        "evidence_quote": "This has been going on for years",
                        "source_role": "user",
                        "source_message_index": 4,
                    }
                }
            }
        },
    ),
    PromptExample(
        name="goals",
        user_message="I want more confidence",
        source_message_index=5,
        previous_assistant_message=None,
        patch={
            "goals": {
                "therapy_goals": [
                    {
                        "value": "more confidence",
                        "evidence_quote": "I want more confidence",
                        "source_role": "user",
                        "source_message_index": 5,
                    }
                ]
            }
        },
    ),
    PromptExample(
        name="functional_impairment",
        user_message="I avoid letters and admin tasks",
        source_message_index=6,
        previous_assistant_message=None,
        patch={
            "presenting_problem": {
                "functional_impairment": {
                    "value": "avoids letters and admin tasks",
                    "evidence_quote": "I avoid letters and admin tasks",
                    "source_role": "user",
                    "source_message_index": 6,
                }
            }
        },
    ),
    PromptExample(
        name="coping",
        user_message="I usually distract myself",
        source_message_index=7,
        previous_assistant_message=None,
        patch={
            "coping": {
                "attempted_strategies": [
                    {
                        "value": "distract myself",
                        "evidence_quote": "I usually distract myself",
                        "source_role": "user",
                        "source_message_index": 7,
                    }
                ]
            }
        },
    ),
    PromptExample(
        name="safety_negative",
        user_message=(
            "No thoughts of harming myself or anyone else, and nothing medically urgent"
        ),
        source_message_index=8,
        previous_assistant_message=(
            "Are you having thoughts of harming yourself or others?"
        ),
        patch={
            "safety": {
                "self_harm": {
                    "value": "none reported",
                    "evidence_quote": "No thoughts of harming myself",
                    "source_role": "user",
                    "source_message_index": 8,
                },
                "harm_to_others": {
                    "value": "none reported",
                    "evidence_quote": "or anyone else",
                    "source_role": "user",
                    "source_message_index": 8,
                },
                "medical_urgency": {
                    "value": "none reported",
                    "evidence_quote": "nothing medically urgent",
                    "source_role": "user",
                    "source_message_index": 8,
                },
            }
        },
    ),
    PromptExample(
        name="unable_to_answer",
        user_message="I don't want to answer that",
        source_message_index=9,
        previous_assistant_message="What are your goals for therapy?",
        patch={
            "goals": {
                "therapy_goals": [
                    {
                        "evidence_quote": "I don't want to answer that",
                        "source_role": "user",
                        "source_message_index": 9,
                        "response_status": "unable_to_answer",
                        "direct_ask": True,
                    }
                ]
            }
        },
    ),
    PromptExample(
        name="unknown",
        user_message="I don't know",
        source_message_index=10,
        previous_assistant_message="How long has this been going on?",
        patch={
            "presenting_problem": {
                "time_course": {
                    "duration_or_onset": {
                        "evidence_quote": "I don't know",
                        "source_role": "user",
                        "source_message_index": 10,
                        "response_status": "unknown",
                        "direct_ask": True,
                    }
                }
            }
        },
    ),
    PromptExample(
        name="no_new_information",
        user_message="Thanks, that makes sense",
        source_message_index=11,
        previous_assistant_message=None,
        patch={"no_new_information": True},
    ),
)


_LIST_EVIDENCE_PATHS: frozenset[str] | None = None


def intake_patch_top_level_fields() -> frozenset[str]:
    return frozenset(IntakeRecordPatch.model_fields.keys())


def intake_evidence_fields() -> frozenset[str]:
    return frozenset(IntakeEvidence.model_fields.keys())


def intake_evidence_required_for_informative() -> frozenset[str]:
    return frozenset(
        {"value", "evidence_quote", "source_role", "source_message_index"}
    )


def intake_patch_evidence_paths() -> frozenset[str]:
    paths: set[str] = set()
    list_paths: set[str] = set()
    _collect_evidence_paths(
        IntakeRecordPatch,
        prefix="",
        paths=paths,
        list_paths=list_paths,
    )
    global _LIST_EVIDENCE_PATHS
    _LIST_EVIDENCE_PATHS = frozenset(list_paths)
    return frozenset(paths)


def render_patch_shape_block() -> str:
    top_level = sorted(intake_patch_top_level_fields())
    evidence_lines = sorted(_evidence_path_lines())
    lines = [
        "Top-level keys:",
        *[f"- {name}" for name in top_level],
        "",
        "Evidence paths:",
        *evidence_lines,
    ]
    return "\n".join(lines)


def render_field_guidance_block() -> str:
    lines = [
        "FIELD GUIDANCE:",
        *[
            f"- {path}: {guidance}"
            for path, guidance in sorted(FIELD_GUIDANCE_BY_PATH.items())
        ],
    ]
    return "\n".join(lines)


def render_prompt_examples() -> str:
    blocks: list[str] = []
    for example in NOTE_TRACKING_PROMPT_EXAMPLES:
        patch_json = json.dumps(example.patch, sort_keys=True, ensure_ascii=True)
        context = (
            f"Previous therapist: {example.previous_assistant_message}"
            if example.previous_assistant_message
            else "Previous therapist: (none)"
        )
        blocks.append(
            "\n".join(
                [
                    f"Example: {example.name}",
                    context,
                    f"Patient: {example.user_message}",
                    patch_json,
                ]
            )
        )
    return "EXAMPLES:\n\n" + "\n\n".join(blocks)


def format_intake_note_tracking_prompt(
    *,
    current_record: IntakeRecord,
    latest_user_message: str,
    source_message_index: int,
    previous_assistant_message: str | None = None,
) -> str:
    current_record_json = json.dumps(
        current_record.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=True,
    )
    previous_assistant_message_text = previous_assistant_message or ""
    return INTAKE_NOTE_TRACKING_PROMPT.format(
        patch_shape=render_patch_shape_block(),
        field_guidance=render_field_guidance_block(),
        examples=render_prompt_examples(),
        current_record_json=current_record_json,
        previous_assistant_message=previous_assistant_message_text,
        latest_user_message=latest_user_message,
        source_message_index=source_message_index,
    )


def _evidence_path_lines() -> list[str]:
    lines: list[str] = []
    for path in sorted(intake_patch_evidence_paths()):
        if _is_list_evidence_path(path):
            lines.append(f"- {path}: list[IntakeEvidence]")
        else:
            lines.append(f"- {path}: IntakeEvidence")
    return lines


def _is_list_evidence_path(path: str) -> bool:
    if _LIST_EVIDENCE_PATHS is None:
        intake_patch_evidence_paths()
    assert _LIST_EVIDENCE_PATHS is not None
    return path in _LIST_EVIDENCE_PATHS


def _collect_evidence_paths(
    model: type[BaseModel],
    *,
    prefix: str,
    paths: set[str],
    list_paths: set[str],
) -> None:
    for field_name, field_info in model.model_fields.items():
        annotation = _unwrap_annotation(field_info.annotation)
        path = f"{prefix}.{field_name}" if prefix else field_name

        if annotation is IntakeEvidence:
            paths.add(path)
            continue

        if _is_list_annotation(annotation):
            item_type = _unwrap_annotation(get_args(annotation)[0])
            if item_type is IntakeEvidence:
                paths.add(path)
                list_paths.add(path)
            continue

        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            _collect_evidence_paths(
                annotation,
                prefix=path,
                paths=paths,
                list_paths=list_paths,
            )


def _unwrap_annotation(annotation: Any) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Union or origin is UnionType:
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _unwrap_annotation(non_none[0])
        return annotation

    if origin is list and args:
        return list[_unwrap_annotation(args[0])]  # type: ignore[misc, valid-type]

    return annotation


def _is_list_annotation(annotation: Any) -> bool:
    return get_origin(_unwrap_annotation(annotation)) is list
