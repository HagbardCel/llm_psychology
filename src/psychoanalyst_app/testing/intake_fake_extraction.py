"""Deterministic fake IntakeRecordPatch extraction for probes and tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

TARGET_GOALS = "goals.therapy_goals"
TARGET_DURATION = "presenting_problem.time_course.duration_or_onset"
TARGET_SAFETY_SELF_HARM = "safety.self_harm"
TARGET_SAFETY_HARM_TO_OTHERS = "safety.harm_to_others"
TARGET_SAFETY_MEDICAL_URGENCY = "safety.medical_urgency"

ALL_SAFETY_TARGETS = (
    TARGET_SAFETY_SELF_HARM,
    TARGET_SAFETY_HARM_TO_OTHERS,
    TARGET_SAFETY_MEDICAL_URGENCY,
)

_PREVIOUS_MESSAGE_RE = re.compile(
    r"PREVIOUS THERAPIST MESSAGE:\s*(?P<previous>.*?)\n\s*LATEST PATIENT MESSAGE:",
    re.DOTALL,
)
_LATEST_MESSAGE_RE = re.compile(
    r"LATEST PATIENT MESSAGE:\s*(?P<message>.*?)\n\s*SOURCE MESSAGE INDEX:",
    re.DOTALL,
)
_SOURCE_INDEX_RE = re.compile(r"SOURCE MESSAGE INDEX:\s*(?P<index>\d+)")
_DURATION_RE = re.compile(
    r"\bfor\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
    r"(day|days|week|weeks|month|months|year|years)\b",
    re.IGNORECASE,
)

_VALUE_MAIN_CONCERN = "anxiety / procrastination / stress"
_VALUE_DURATION = "reported duration or onset"
_VALUE_GOALS = "improve confidence / sleep / understanding"
_VALUE_FUNCTIONAL_IMPAIRMENT = "avoidance or freezing affects functioning"
_VALUE_COPING = "attempted coping strategy"
_VALUE_SAFETY_NONE = "none reported"
_VALUE_SAFETY_RISK = "risk content reported"


@dataclass(frozen=True)
class ParsedPrompt:
    latest_user_message: str
    source_message_index: int
    previous_therapist_message: str
    is_valid: bool


def parse_prompt_anchors(prompt: str) -> ParsedPrompt:
    """Parse note-tracking prompt anchors from a rendered prompt."""
    latest_match = _LATEST_MESSAGE_RE.search(prompt or "")
    index_match = _SOURCE_INDEX_RE.search(prompt or "")
    previous_match = _PREVIOUS_MESSAGE_RE.search(prompt or "")

    latest = latest_match.group("message").strip() if latest_match else ""
    previous = previous_match.group("previous").strip() if previous_match else ""
    index: int | None = None
    if index_match:
        index = int(index_match.group("index"))

    is_valid = bool(latest) and index is not None
    return ParsedPrompt(
        latest_user_message=latest,
        source_message_index=index if index is not None else 0,
        previous_therapist_message=previous,
        is_valid=is_valid,
    )


def build_fake_intake_patch_payload(prompt: str) -> dict[str, Any]:
    """Return a deterministic IntakeRecordPatch payload for probe transcripts."""
    parsed = parse_prompt_anchors(prompt)
    if not parsed.is_valid:
        return {"no_new_information": True}

    message = parsed.latest_user_message
    message_lower = message.lower()
    previous_lower = parsed.previous_therapist_message.lower()
    index = parsed.source_message_index

    if _is_unable_to_answer(message_lower):
        return _direct_answer_patch(
            _targets_for_previous_message(previous_lower),
            quote=message,
            index=index,
            status="unable_to_answer",
        )
    if _is_unknown(message_lower):
        return _direct_answer_patch(
            _targets_for_previous_message(previous_lower),
            quote=message,
            index=index,
            status="unknown",
        )
    if safety_patch := _safety_patch(message_lower, quote=message, index=index):
        return safety_patch
    if _is_duration(message_lower):
        return _duration_patch(quote=message, index=index)
    if _is_functional_impairment(message_lower):
        return _functional_impairment_patch(quote=message, index=index)
    if _is_goals(message_lower):
        return _goals_patch(quote=message, index=index)
    if _is_coping(message_lower):
        return _coping_patch(quote=message, index=index)
    if _is_presenting_problem(message_lower):
        return _presenting_problem_patch(quote=message, index=index)
    return {"no_new_information": True}


def _evidence(
    *,
    quote: str,
    index: int,
    value: str | None = None,
    status: Literal["informative", "unknown", "unable_to_answer"] = "informative",
    direct_ask: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "evidence_quote": quote,
        "source_role": "user",
        "source_message_index": index,
        "response_status": status,
    }
    if value is not None:
        payload["value"] = value
    if direct_ask:
        payload["direct_ask"] = True
    return payload


def _presenting_problem_patch(*, quote: str, index: int) -> dict[str, Any]:
    return {
        "presenting_problem": {
            "main_concern": _evidence(
                value=_VALUE_MAIN_CONCERN,
                quote=quote,
                index=index,
            )
        }
    }


def _duration_patch(*, quote: str, index: int) -> dict[str, Any]:
    return {
        "presenting_problem": {
            "time_course": {
                "duration_or_onset": _evidence(
                    value=_VALUE_DURATION,
                    quote=quote,
                    index=index,
                )
            }
        }
    }


def _goals_patch(*, quote: str, index: int) -> dict[str, Any]:
    return {
        "goals": {
            "therapy_goals": [
                _evidence(value=_VALUE_GOALS, quote=quote, index=index)
            ]
        }
    }


def _functional_impairment_patch(*, quote: str, index: int) -> dict[str, Any]:
    return {
        "presenting_problem": {
            "functional_impairment": _evidence(
                value=_VALUE_FUNCTIONAL_IMPAIRMENT,
                quote=quote,
                index=index,
            )
        }
    }


def _coping_patch(*, quote: str, index: int) -> dict[str, Any]:
    return {
        "coping": {
            "attempted_strategies": [
                _evidence(value=_VALUE_COPING, quote=quote, index=index)
            ]
        }
    }


def _safety_patch(
    message_lower: str,
    *,
    quote: str,
    index: int,
) -> dict[str, Any] | None:
    fields = _safety_fields_for_message(message_lower)
    if not fields:
        return None

    denial = _is_safety_denial(message_lower)
    value = _VALUE_SAFETY_NONE if denial else _VALUE_SAFETY_RISK
    safety: dict[str, Any] = {}
    for target in fields:
        field_name = target.rsplit(".", maxsplit=1)[-1]
        safety[field_name] = _evidence(value=value, quote=quote, index=index)
    return {"safety": safety}


def _direct_answer_patch(
    targets: tuple[str, ...],
    *,
    quote: str,
    index: int,
    status: Literal["unknown", "unable_to_answer"],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for target in targets:
        evidence = _evidence(
            quote=quote,
            index=index,
            status=status,
            direct_ask=True,
        )
        if target == TARGET_GOALS:
            payload.setdefault("goals", {})["therapy_goals"] = [evidence]
        elif target == TARGET_DURATION:
            payload.setdefault("presenting_problem", {}).setdefault(
                "time_course", {}
            )["duration_or_onset"] = evidence
        elif target == TARGET_SAFETY_SELF_HARM:
            payload.setdefault("safety", {})["self_harm"] = evidence
        elif target == TARGET_SAFETY_HARM_TO_OTHERS:
            payload.setdefault("safety", {})["harm_to_others"] = evidence
        elif target == TARGET_SAFETY_MEDICAL_URGENCY:
            payload.setdefault("safety", {})["medical_urgency"] = evidence
    return payload


def _targets_for_previous_message(previous_lower: str) -> tuple[str, ...]:
    if "goal" in previous_lower:
        return (TARGET_GOALS,)
    if any(token in previous_lower for token in ("how long", "since", "duration")):
        return (TARGET_DURATION,)
    if any(
        token in previous_lower
        for token in ("safety", "risk", "harm", "urgent", "harming")
    ):
        return ALL_SAFETY_TARGETS
    return (TARGET_DURATION,)


def _is_unable_to_answer(message_lower: str) -> bool:
    return any(
        phrase in message_lower
        for phrase in (
            "don't want to answer",
            "won't answer",
            "rather not say",
            "prefer not to",
        )
    )


def _is_unknown(message_lower: str) -> bool:
    return any(
        phrase in message_lower
        for phrase in ("don't know", "not sure", "no idea")
    )


def _is_duration(message_lower: str) -> bool:
    return (
        _DURATION_RE.search(message_lower) is not None
        or "since" in message_lower
        or "going on for" in message_lower
    )


def _is_functional_impairment(message_lower: str) -> bool:
    return any(
        phrase in message_lower
        for phrase in ("avoid", "can't", "freeze", "freezing", "unable to work")
    )


def _is_goals(message_lower: str) -> bool:
    return any(
        phrase in message_lower
        for phrase in (
            "goal",
            "would like to",
            "hope to",
            "want to get better",
            "want to understand",
            "want more confidence",
            "sleep better",
            "feel less anxious",
        )
    )


def _is_coping(message_lower: str) -> bool:
    return any(
        phrase in message_lower
        for phrase in ("tried", "distract", "breathing", "i usually")
    )


def _is_presenting_problem(message_lower: str) -> bool:
    return any(
        phrase in message_lower
        for phrase in (
            "procrastinat",
            "anxious",
            "anxiety",
            "depress",
            "stress",
            "panic",
        )
    )


def _is_safety_denial(message_lower: str) -> bool:
    return any(
        phrase in message_lower
        for phrase in (
            "no thoughts of harming myself",
            "not thinking of harming myself",
            "have not had thoughts of harming myself",
            "nothing medically urgent",
            "not medically urgent",
        )
    )


def _safety_fields_for_message(message_lower: str) -> tuple[str, ...]:
    if _is_combined_safety_screen(message_lower):
        return ALL_SAFETY_TARGETS

    fields: list[str] = []
    if _matches_self_harm(message_lower):
        fields.append(TARGET_SAFETY_SELF_HARM)
    if _matches_harm_to_others(message_lower):
        fields.append(TARGET_SAFETY_HARM_TO_OTHERS)
    if _matches_medical_urgency(message_lower):
        fields.append(TARGET_SAFETY_MEDICAL_URGENCY)
    return tuple(fields)


def _is_combined_safety_screen(message_lower: str) -> bool:
    if not _is_safety_denial(message_lower):
        return False
    has_self_harm_context = any(
        phrase in message_lower
        for phrase in ("harm myself", "harming myself", "hurt myself")
    )
    has_other_context = any(
        phrase in message_lower
        for phrase in (
            "harm anyone else",
            "hurt anyone else",
            "or anyone else",
            "harm others",
            "hurt others",
        )
    )
    has_medical_context = "medically urgent" in message_lower
    return has_self_harm_context and has_other_context and has_medical_context


def _matches_self_harm(message_lower: str) -> bool:
    return any(
        phrase in message_lower
        for phrase in (
            "harm myself",
            "harming myself",
            "hurt myself",
            "kill myself",
            "suicidal",
            "suicide",
        )
    )


def _matches_harm_to_others(message_lower: str) -> bool:
    return any(
        phrase in message_lower
        for phrase in (
            "harm others",
            "hurt others",
            "hurt someone",
            "harm anyone else",
            "hurt anyone else",
        )
    )


def _matches_medical_urgency(message_lower: str) -> bool:
    return any(
        phrase in message_lower
        for phrase in (
            "medically urgent",
            "medical emergency",
            "immediate danger",
        )
    )
