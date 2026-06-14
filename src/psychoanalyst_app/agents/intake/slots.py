"""Intake slot/topic detection helpers and constants."""

from __future__ import annotations

import logging
from datetime import datetime

from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.orchestration.models import ConversationContext
from psychoanalyst_app.shared.intake_slot_evidence import (
    COPING_ATTEMPTS_PROMPT,
    GOAL_PREFERENCE_PROMPT,
    HARD_REQUIRED_INTAKE_SLOTS,
    REQUIRED_INTAKE_SLOTS,
    RISK_SCREEN_PROMPT,
    SOFT_REQUIRED_INTAKE_SLOTS,
    EvidenceMessage,
    SlotEvidence,
    covered_slots_from_evidence,
    intake_slot_evidence_from_messages,
    next_required_follow_up_slot,
)

from psychoanalyst_app.agents.intake.policy import (
    MAX_INTAKE_PATIENT_TURNS,
    MIN_INTAKE_PATIENT_TURNS,
)

logger = logging.getLogger(__name__)

__all__ = [
    "COPING_ATTEMPTS_PROMPT",
    "GOAL_PREFERENCE_PROMPT",
    "HARD_REQUIRED_INTAKE_SLOTS",
    "MAX_INTAKE_PATIENT_TURNS",
    "MIN_INTAKE_PATIENT_TURNS",
    "REQUIRED_INTAKE_SLOTS",
    "RISK_SCREEN_PROMPT",
    "SOFT_REQUIRED_INTAKE_SLOTS",
    "SlotEvidence",
    "identify_covered_topics",
    "identify_required_slots",
    "intake_completion_diagnostics",
    "intake_slot_evidence",
    "is_intake_complete",
    "next_required_follow_up",
    "next_required_follow_up_slot",
    "patient_messages",
]


def _conversation_evidence_messages(
    message: str,
    message_history: list[Message],
) -> list[EvidenceMessage]:
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
        EvidenceMessage(role=item.role, content=item.content)
        for item in evidence_history
    ]


def patient_messages(message: str, message_history: list[Message]) -> list[Message]:
    """Return patient-authored evidence without duplicating the current turn."""
    messages = [item for item in message_history if item.role == "user"]
    if message.strip() and (not messages or messages[-1].content != message):
        messages.append(Message(role="user", content=message, timestamp=datetime.now()))
    return messages


def identify_required_slots(message: str, message_history: list[Message]) -> set[str]:
    """Derive completion slots from patient answers and explicit follow-ups."""
    evidence = intake_slot_evidence(message, message_history)
    return covered_slots_from_evidence(evidence)


def intake_slot_evidence(
    message: str, message_history: list[Message]
) -> dict[str, SlotEvidence]:
    """Return auditable evidence for each intake slot."""
    return intake_slot_evidence_from_messages(
        _conversation_evidence_messages(message, message_history)
    )


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


def intake_completion_diagnostics(
    context: ConversationContext,
    intake_slot_coverage: set[str],
) -> dict[str, object]:
    """Build auditable intake completion diagnostics for logs and probes."""
    patient_turn_count = len(patient_messages("", context.message_history))
    slot_evidence = intake_slot_evidence("", context.message_history)
    intake_slot_coverage = intake_slot_coverage & covered_slots_from_evidence(
        slot_evidence
    )
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
