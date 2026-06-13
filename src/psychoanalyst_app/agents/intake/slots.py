"""Intake slot/topic detection helpers and constants."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Literal, TypedDict

from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.orchestration.models import ConversationContext

logger = logging.getLogger(__name__)

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
MIN_INTAKE_PATIENT_TURNS = 3
MAX_INTAKE_PATIENT_TURNS = 12
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

SlotStatus = Literal["missing", "partial", "covered"]
SlotExplicitness = Literal["explicit", "inferred", "not_present"]


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


def _patient_evidence_history(
    message: str,
    message_history: list[Message],
) -> list[tuple[int, Message]]:
    evidence_history = list(message_history)
    if message.strip() and (
        not evidence_history
        or evidence_history[-1].role != "user"
        or evidence_history[-1].content != message
    ):
        evidence_history.append(
            Message(role="user", content=message, timestamp=datetime.now())
        )
    return [
        (index, item)
        for index, item in enumerate(evidence_history)
        if item.role == "user"
    ]


def _find_keyword_evidence(
    slot_id: str,
    messages: list[tuple[int, Message]],
) -> SlotEvidence:
    keywords = SLOT_KEYWORDS[slot_id]
    for index, item in messages:
        content = item.content.lower()
        if any(keyword in content for keyword in keywords):
            return _covered_evidence(slot_id, message_index=index, quote=item.content)
    return _missing_evidence(slot_id, "No explicit patient evidence found")


def _find_duration_evidence(messages: list[tuple[int, Message]]) -> SlotEvidence:
    for index, item in messages:
        content = item.content.lower()
        if any(pattern.search(content) for pattern in DURATION_PATTERNS):
            return _covered_evidence(
                "duration",
                message_index=index,
                quote=item.content,
            )
    return _missing_evidence(
        "duration",
        "No patient statement specifies onset, duration, or frequency",
    )


def _find_prompt_answer_evidence(
    slot_id: str,
    message: str,
    message_history: list[Message],
    *,
    prompt: str,
    answer_keywords: tuple[str, ...],
) -> SlotEvidence:
    evidence_history = list(message_history)
    if message.strip() and (
        not evidence_history
        or evidence_history[-1].role != "user"
        or evidence_history[-1].content != message
    ):
        evidence_history.append(
            Message(role="user", content=message, timestamp=datetime.now())
        )
    for index, item in enumerate(evidence_history):
        if item.role != "assistant" or index + 1 >= len(evidence_history):
            continue
        answer = evidence_history[index + 1]
        if answer.role != "user" or not answer.content.strip():
            continue
        if item.content == prompt and any(
            keyword in answer.content.lower() for keyword in answer_keywords
        ):
            return _covered_evidence(
                slot_id,
                message_index=index + 1,
                quote=answer.content,
            )
    return _missing_evidence(slot_id, "No explicit patient answer to required prompt")


def patient_messages(message: str, message_history: list[Message]) -> list[Message]:
    """Return patient-authored evidence without duplicating the current turn."""
    messages = [item for item in message_history if item.role == "user"]
    if message.strip() and (not messages or messages[-1].content != message):
        messages.append(Message(role="user", content=message, timestamp=datetime.now()))
    return messages


def identify_required_slots(message: str, message_history: list[Message]) -> set[str]:
    """Derive completion slots from patient answers and explicit follow-ups."""
    evidence = intake_slot_evidence(message, message_history)
    return {
        slot
        for slot, detail in evidence.items()
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


def intake_slot_evidence(
    message: str, message_history: list[Message]
) -> dict[str, SlotEvidence]:
    """Return auditable evidence for each intake slot."""
    messages = _patient_evidence_history(message, message_history)
    evidence: dict[str, SlotEvidence] = {
        slot: _missing_evidence(slot, "No explicit patient evidence found")
        for slot in REQUIRED_INTAKE_SLOTS
    }

    for slot in SLOT_KEYWORDS:
        evidence[slot] = _find_keyword_evidence(slot, messages)
    evidence["duration"] = _find_duration_evidence(messages)
    evidence["risk_screen"] = _find_prompt_answer_evidence(
        "risk_screen",
        message,
        message_history,
        prompt=RISK_SCREEN_PROMPT,
        answer_keywords=(
            "harm",
            "suicid",
            "hurt myself",
            "hurt anyone",
            "safe",
            "urgent",
            "medical",
            "chest",
        ),
    )
    evidence["goal_preference"] = _find_prompt_answer_evidence(
        "goal_preference",
        message,
        message_history,
        prompt=GOAL_PREFERENCE_PROMPT,
        answer_keywords=("goal", "want", "hope", "start", "different", "better"),
    )
    return evidence


def identify_covered_topics(message: str, message_history: list[Message]) -> list[str]:
    """Analyze conversation to identify which topics were covered."""
    p_messages = patient_messages(message, message_history)
    combined_text = " ".join(msg.content.lower() for msg in p_messages)
    logger.info(f"Combined text for topic analysis: {combined_text}")

    covered: list[str] = []
    topic_keywords = {
        "Presenting Problem": [
            "problem",
            "issue",
            "concern",
            "struggling",
            "difficulty",
        ],
        "Current Symptoms": ["symptom", "feeling", "experience", "happening"],
        "Personal History": [
            "history",
            "past",
            "childhood",
            "grew up",
            "background",
        ],
        "Family Background": ["family", "parents", "siblings", "mother", "father"],
        "Relationships": ["relationship", "partner", "spouse", "friend", "dating"],
        "Work/School": ["work", "job", "school", "career", "colleague", "boss"],
        "Physical Health": ["health", "medical", "physical", "doctor", "illness"],
        "Mental Health History": [
            "depression",
            "anxiety",
            "therapy",
            "counseling",
            "medication",
        ],
        "Substance Use": ["alcohol", "drug", "substance", "drinking", "smoking"],
        "Coping Mechanisms": ["cope", "deal with", "handle", "manage", "stress"],
        "Support System": ["support", "help", "friend", "family support"],
        "Goals for Therapy": ["goal", "hope", "want", "expect", "looking for"],
    }

    for topic, keywords in topic_keywords.items():
        if any(keyword in combined_text for keyword in keywords):
            covered.append(topic)
            logger.info(f"Matched topic: {topic}")

    return covered


def next_required_follow_up(intake_slot_coverage: set[str]) -> str | None:
    """Return direct follow-ups for critical slots that must not be skipped."""
    if "risk_screen" not in intake_slot_coverage:
        return RISK_SCREEN_PROMPT
    if "goal_preference" not in intake_slot_coverage:
        return GOAL_PREFERENCE_PROMPT
    if "coping_attempts" not in intake_slot_coverage:
        return COPING_ATTEMPTS_PROMPT
    return None


def next_required_follow_up_slot(intake_slot_coverage: set[str]) -> str | None:
    """Return the slot name for the next direct follow-up, if any."""
    if "risk_screen" not in intake_slot_coverage:
        return "risk_screen"
    if "goal_preference" not in intake_slot_coverage:
        return "goal_preference"
    if "coping_attempts" not in intake_slot_coverage:
        return "coping_attempts"
    return None


def intake_completion_diagnostics(
    context: ConversationContext,
    intake_slot_coverage: set[str],
) -> dict[str, object]:
    """Build auditable intake completion diagnostics for logs and probes."""
    patient_turn_count = len(patient_messages("", context.message_history))
    slot_evidence = intake_slot_evidence("", context.message_history)
    evidence_backed_coverage = {
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
    intake_slot_coverage = intake_slot_coverage & evidence_backed_coverage
    missing_required = REQUIRED_INTAKE_SLOTS - intake_slot_coverage
    missing_hard = HARD_REQUIRED_INTAKE_SLOTS - intake_slot_coverage
    missing_soft = SOFT_REQUIRED_INTAKE_SLOTS - intake_slot_coverage
    complete = (
        not missing_required and patient_turn_count >= MIN_INTAKE_PATIENT_TURNS
    ) or (
        not missing_hard and patient_turn_count >= MAX_INTAKE_PATIENT_TURNS
    )
    if complete:
        completion_decision = "complete_intake"
    elif missing_hard:
        completion_decision = "continue_intake_missing_hard_slots"
    else:
        completion_decision = "continue_intake_missing_soft_slots"

    return {
        "patient_turn_count": patient_turn_count,
        "covered_slots": sorted(intake_slot_coverage),
        "slot_evidence": slot_evidence,
        "missing_required_slots": sorted(missing_required),
        "missing_hard_slots": sorted(missing_hard),
        "missing_soft_slots": sorted(missing_soft),
        "next_required_follow_up": next_required_follow_up_slot(
            intake_slot_coverage
        ),
        "completion_decision": completion_decision,
        "max_turn_completion": bool(
            complete
            and missing_soft
            and not missing_hard
            and patient_turn_count >= MAX_INTAKE_PATIENT_TURNS
        ),
    }


def is_intake_complete(
    context: ConversationContext, intake_slot_coverage: set[str]
) -> bool:
    """Check whether the intake objectives have been met."""
    diagnostics = intake_completion_diagnostics(context, intake_slot_coverage)
    patient_turn_count = int(diagnostics["patient_turn_count"])
    missing_hard = set(diagnostics["missing_hard_slots"])
    missing_soft = set(diagnostics["missing_soft_slots"])

    if (
        not missing_hard
        and not missing_soft
        and patient_turn_count >= MIN_INTAKE_PATIENT_TURNS
    ):
        logger.info(
            "Intake complete: %s slots covered across %s patient turns",
            len(intake_slot_coverage),
            patient_turn_count,
        )
        return True

    if not missing_hard and patient_turn_count >= MAX_INTAKE_PATIENT_TURNS:
        logger.warning(
            "Completing intake after max turns with missing soft slots: %s",
            sorted(missing_soft),
        )
        return True

    min_duration = context.duration_minutes * 0.5
    if context.time_elapsed_minutes < min_duration:
        if patient_turn_count >= MIN_INTAKE_PATIENT_TURNS:
            logger.info("Intake completion pending: %s", diagnostics)
        return False

    if patient_turn_count >= MIN_INTAKE_PATIENT_TURNS:
        logger.info("Intake completion pending: %s", diagnostics)
    return False
