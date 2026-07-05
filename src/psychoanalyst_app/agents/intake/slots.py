"""Intake topic detection helpers."""

from __future__ import annotations

import logging
from datetime import datetime

from psychoanalyst_app.models.domain import Message

logger = logging.getLogger(__name__)

__all__ = [
    "identify_covered_topics",
    "patient_messages",
]


def patient_messages(message: str, message_history: list[Message]) -> list[Message]:
    """Return patient-authored evidence without duplicating the current turn."""
    messages = [item for item in message_history if item.role == "user"]
    if message.strip() and (not messages or messages[-1].content != message):
        messages.append(Message(role="user", content=message, timestamp=datetime.now()))
    return messages


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
