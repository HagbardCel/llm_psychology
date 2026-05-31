"""Intake slot/topic detection helpers and constants."""

from __future__ import annotations

import logging
from datetime import datetime

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
MIN_INTAKE_PATIENT_TURNS = 3
RISK_SCREEN_PROMPT = (
    "Before we continue, I want to check your safety directly. Have you had any "
    "thoughts of harming yourself or someone else? Also, when physical symptoms "
    "such as chest tightness occur, do they ever feel medically urgent?"
)
GOAL_PREFERENCE_PROMPT = (
    "What would you most want to be different as a result of therapy, and what "
    "would feel like the most useful place for us to start?"
)


def patient_messages(message: str, message_history: list[Message]) -> list[Message]:
    """Return patient-authored evidence without duplicating the current turn."""
    messages = [item for item in message_history if item.role == "user"]
    if message.strip() and (not messages or messages[-1].content != message):
        messages.append(Message(role="user", content=message, timestamp=datetime.now()))
    return messages


def identify_required_slots(message: str, message_history: list[Message]) -> set[str]:
    """Derive completion slots from patient answers and explicit follow-ups."""
    p_messages = patient_messages(message, message_history)
    combined_text = " ".join(item.content.lower() for item in p_messages)
    slots: set[str] = set()
    slot_keywords = {
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
        "duration": [
            "week",
            "month",
            "year",
            "lately",
            "recently",
            "since",
            "for ",
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
            "exercise",
            "breathing",
            "meditation",
            "avoid",
            "alcohol",
            "wine",
            "caffeine",
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
        ],
    }
    for slot, keywords in slot_keywords.items():
        if any(keyword in combined_text for keyword in keywords):
            slots.add(slot)

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
        answer_text = answer.content.lower()
        if item.content == RISK_SCREEN_PROMPT and any(
            keyword in answer_text
            for keyword in (
                "harm",
                "suicid",
                "hurt myself",
                "hurt anyone",
                "safe",
                "urgent",
                "medical",
                "chest",
            )
        ):
            slots.add("risk_screen")
        if item.content == GOAL_PREFERENCE_PROMPT and any(
            keyword in answer_text
            for keyword in ("goal", "want", "hope", "start", "different", "better")
        ):
            slots.add("goal_preference")
    return slots


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
    return None


def is_intake_complete(
    context: ConversationContext, intake_slot_coverage: set[str]
) -> bool:
    """Check whether the intake objectives have been met."""
    patient_turn_count = len(patient_messages("", context.message_history))
    slots_complete = REQUIRED_INTAKE_SLOTS <= intake_slot_coverage
    if slots_complete and patient_turn_count >= MIN_INTAKE_PATIENT_TURNS:
        logger.info(
            "Intake complete: %s slots covered across %s patient turns",
            len(intake_slot_coverage),
            patient_turn_count,
        )
        return True

    min_duration = context.duration_minutes * 0.5
    if context.time_elapsed_minutes < min_duration:
        return False

    return False
