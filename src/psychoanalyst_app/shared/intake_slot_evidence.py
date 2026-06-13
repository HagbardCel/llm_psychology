"""Pure intake slot-evidence detection for backend and workflow probes."""

from __future__ import annotations

import re
from typing import Any, Literal, Mapping, Sequence, TypedDict

REQUIRED_INTAKE_SLOTS = {
    "presenting_problem",
    "duration",
    "sleep_impact",
    "coping_attempts",
    "functional_impairment",
    "risk_screen",
    "goal_preference",
}
HARD_REQUIRED_INTAKE_SLOTS = {
    "presenting_problem",
    "duration",
    "functional_impairment",
    "risk_screen",
    "goal_preference",
}
SOFT_REQUIRED_INTAKE_SLOTS = REQUIRED_INTAKE_SLOTS - HARD_REQUIRED_INTAKE_SLOTS
RISK_SCREEN_PROMPT = (
    "Before we continue, I want to check your safety directly. Have you had any "
    "thoughts of harming yourself or someone else? Also, when physical symptoms "
    "such as chest tightness occur, do they ever feel medically urgent?"
)
GOAL_PREFERENCE_PROMPT = (
    "What would you most want to be different as a result of therapy, and what "
    "would feel like the most useful place for us to start?"
)
COPING_ATTEMPTS_PROMPT = (
    "Before we close the intake, I need one practical detail: what have you "
    "already tried to manage the anxiety, racing thoughts, or sleep difficulty? "
    "For example: avoidance, breathing, exercise, meditation, alcohol, sleep "
    "medication, talking to someone, or nothing yet."
)
RISK_SCREEN_ANSWER_KEYWORDS = (
    "harm",
    "suicid",
    "hurt myself",
    "hurt anyone",
    "safe",
    "urgent",
    "medical",
    "chest",
)
GOAL_PREFERENCE_ANSWER_KEYWORDS = (
    "goal",
    "want",
    "hope",
    "start",
    "different",
    "better",
)

SlotStatus = Literal["missing", "partial", "covered"]
SlotExplicitness = Literal["explicit", "inferred", "not_present"]


class EvidenceMessage(TypedDict):
    role: str
    content: str


class SlotEvidence(TypedDict):
    slot_id: str
    status: SlotStatus
    explicitness: SlotExplicitness
    evidence_message_index: int | None
    evidence_role: str | None
    evidence_quote: str | None
    confidence: float
    reason: str | None


SLOT_KEYWORDS = {
    "presenting_problem": [
        "anxiety",
        "anxious",
        "worry",
        "worried",
        "stress",
        "dreading",
        "struggling",
        "problem",
        "panic",
    ],
    "sleep_impact": [
        "sleep",
        "insomnia",
        "awake",
        "ceiling",
        "bed",
        "tired",
    ],
    "coping_attempts": [
        "cope",
        "coping",
        "try",
        "tried",
        "not tried",
        "haven't tried",
        "have not tried",
        "nothing yet",
        "anything yet",
        "exercise",
        "breathing",
        "meditation",
        "avoid",
        "avoiding",
        "alcohol",
        "wine",
        "caffeine",
        "medication",
        "talking to someone",
        "substance",
    ],
    "functional_impairment": [
        "work",
        "deadline",
        "project",
        "school",
        "focus",
        "concentrate",
        "relationship",
        "function",
        "miss meetings",
        "missed meetings",
        "can't speak",
        "cannot speak",
    ],
}

DURATION_PATTERNS = [
    re.compile(
        r"\b(for|over|about|around|roughly|nearly|almost)\s+"
        r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|several|a few)\s+"
        r"(day|days|week|weeks|month|months|year|years)\b"
    ),
    re.compile(r"\bsince\s+[a-z0-9][a-z0-9 ,/-]{1,40}\b"),
    re.compile(
        r"\b(twice|once|daily|nightly|weekly|monthly|every\s+"
        r"(day|night|week|month)|\d+\s+times\s+(a|per)\s+"
        r"(day|week|month|year))\b"
    ),
    re.compile(r"\b(last|past)\s+(few|couple|several|\d+)\s+(days|weeks|months|years)\b"),
]


def _missing_evidence(slot_id: str, reason: str) -> SlotEvidence:
    return {
        "slot_id": slot_id,
        "status": "missing",
        "explicitness": "not_present",
        "evidence_message_index": None,
        "evidence_role": None,
        "evidence_quote": None,
        "confidence": 0.0,
        "reason": reason,
    }


def _covered_evidence(
    slot_id: str,
    *,
    message_index: int,
    quote: str,
    confidence: float = 1.0,
) -> SlotEvidence:
    return {
        "slot_id": slot_id,
        "status": "covered",
        "explicitness": "explicit",
        "evidence_message_index": message_index,
        "evidence_role": "user",
        "evidence_quote": _quote_excerpt(quote),
        "confidence": confidence,
        "reason": None,
    }


def _quote_excerpt(text: str, *, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 13].rstrip() + " <truncated>"


def _user_messages_with_indices(
    messages: Sequence[EvidenceMessage],
) -> list[tuple[int, EvidenceMessage]]:
    return [
        (index, item)
        for index, item in enumerate(messages)
        if item["role"] == "user"
    ]


def _find_keyword_evidence(
    slot_id: str,
    messages: Sequence[EvidenceMessage],
) -> SlotEvidence:
    keywords = SLOT_KEYWORDS[slot_id]
    for index, item in _user_messages_with_indices(messages):
        content = item["content"].lower()
        if any(keyword in content for keyword in keywords):
            return _covered_evidence(
                slot_id, message_index=index, quote=item["content"]
            )
    return _missing_evidence(slot_id, "No explicit patient evidence found")


def _find_duration_evidence(messages: Sequence[EvidenceMessage]) -> SlotEvidence:
    for index, item in _user_messages_with_indices(messages):
        content = item["content"].lower()
        if any(pattern.search(content) for pattern in DURATION_PATTERNS):
            return _covered_evidence(
                "duration",
                message_index=index,
                quote=item["content"],
            )
    return _missing_evidence(
        "duration",
        "No patient statement specifies onset, duration, or frequency",
    )


def _find_prompt_answer_evidence(
    slot_id: str,
    messages: Sequence[EvidenceMessage],
    *,
    prompt: str,
    answer_keywords: tuple[str, ...],
) -> SlotEvidence:
    message_list = list(messages)
    for index, item in enumerate(message_list):
        if item["role"] != "assistant" or index + 1 >= len(message_list):
            continue
        answer = message_list[index + 1]
        if answer["role"] != "user" or not answer["content"].strip():
            continue
        if item["content"] == prompt and any(
            keyword in answer["content"].lower() for keyword in answer_keywords
        ):
            return _covered_evidence(
                slot_id,
                message_index=index + 1,
                quote=answer["content"],
            )
    return _missing_evidence(slot_id, "No explicit patient answer to required prompt")


def intake_slot_evidence_from_messages(
    messages: Sequence[EvidenceMessage],
) -> dict[str, SlotEvidence]:
    """Return auditable evidence for each intake slot from a conversation."""
    evidence: dict[str, SlotEvidence] = {
        slot: _missing_evidence(slot, "No explicit patient evidence found")
        for slot in REQUIRED_INTAKE_SLOTS
    }

    for slot in SLOT_KEYWORDS:
        evidence[slot] = _find_keyword_evidence(slot, messages)
    evidence["duration"] = _find_duration_evidence(messages)
    evidence["risk_screen"] = _find_prompt_answer_evidence(
        "risk_screen",
        messages,
        prompt=RISK_SCREEN_PROMPT,
        answer_keywords=RISK_SCREEN_ANSWER_KEYWORDS,
    )
    evidence["goal_preference"] = _find_prompt_answer_evidence(
        "goal_preference",
        messages,
        prompt=GOAL_PREFERENCE_PROMPT,
        answer_keywords=GOAL_PREFERENCE_ANSWER_KEYWORDS,
    )
    return evidence


def intake_slot_evidence_from_transcript(
    transcript: list[dict[str, Any]],
) -> dict[str, SlotEvidence]:
    """Return auditable evidence from probe/session transcript dicts."""
    messages: list[EvidenceMessage] = []
    for item in transcript:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        messages.append(
            EvidenceMessage(role=str(role), content=str(item.get("content") or ""))
        )
    return intake_slot_evidence_from_messages(messages)


def covered_slots_from_evidence(
    slot_evidence: Mapping[str, SlotEvidence],
) -> set[str]:
    """Return slots with evidence-backed coverage, including hard-slot gating."""
    return {
        slot
        for slot, detail in slot_evidence.items()
        if detail["status"] == "covered"
        and (
            slot not in HARD_REQUIRED_INTAKE_SLOTS
            or (
                detail["explicitness"] == "explicit"
                and detail["evidence_role"] == "user"
                and bool(detail["evidence_quote"])
            )
        )
    }


def next_required_follow_up_slot(intake_slot_coverage: set[str]) -> str | None:
    """Return the slot name for the next direct follow-up, if any."""
    if "risk_screen" not in intake_slot_coverage:
        return "risk_screen"
    if "goal_preference" not in intake_slot_coverage:
        return "goal_preference"
    if "coping_attempts" not in intake_slot_coverage:
        return "coping_attempts"
    return None
