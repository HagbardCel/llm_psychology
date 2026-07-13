"""Intake prompt construction for patch extraction and response streaming."""

from __future__ import annotations

from jung.domain.models import Profile
from jung.llm.gateway import ChatMessage, ChatRole
from jung.phases.intake.completion import (
    IntakeCompleteness,
    missing_items_from_record,
)
from jung.phases.intake.models import IntakeRecord
from jung.phases.transcript import TranscriptTurn

PROMPT_VERSION = "intake-v1"


def _record_summary(record: IntakeRecord, completeness: IntakeCompleteness) -> str:
    concern = record.presenting_problem.main_concern.value or "not yet established"
    missing = ", ".join(completeness.missing_required_items) or "None"
    return (
        f"Main concern: {concern}\n"
        f"Open required items: {missing}\n"
        f"Next required item: {completeness.next_required_item or 'none'}"
    )


def build_direct_ask_instruction(next_item: str | None) -> str:
    if next_item is None:
        return (
            "Ask one concise clarification question that helps complete the intake "
            "without switching topics."
        )
    if next_item == "risk_screen":
        return (
            "Ask directly whether the patient is having thoughts of harming "
            "themselves, harming someone else, or any urgent medical concern."
        )
    return f"Ask one direct intake question about: {next_item}."


def build_patch_extraction_messages(
    *,
    record: IntakeRecord,
    latest_user_message: TranscriptTurn,
    previous_assistant_message: str | None,
) -> list[ChatMessage]:
    context_parts = [
        "Extract a structured intake patch grounded only in the latest patient message.",
        "Do not infer unsupported facts.",
        "Evidence must reference patient-authored text with source_role=user.",
        f"Use source_message_sequence={latest_user_message.sequence}.",
        f"Current record summary:\n{_record_summary(record, missing_items_from_record(record))}",
        f"Latest patient message:\n{latest_user_message.content}",
    ]
    if previous_assistant_message:
        context_parts.append(
            f"Previous assistant question:\n{previous_assistant_message}"
        )
    return [
        ChatMessage(
            role=ChatRole.SYSTEM,
            content=(
                "You extract patient-grounded intake evidence as JSON. "
                "Return only fields supported by the latest patient turn."
            ),
        ),
        ChatMessage(role=ChatRole.USER, content="\n\n".join(context_parts)),
    ]


def _recent_transcript(
    transcript: tuple[TranscriptTurn, ...],
    *,
    latest_user_message: str | None,
) -> str:
    turns = list(transcript[-6:])
    if latest_user_message and turns and turns[-1].role == "user":
        if turns[-1].content.strip() == latest_user_message.strip():
            turns = turns[:-1]
    return "\n".join(f"{turn.role}: {turn.content}" for turn in turns)


def build_response_messages(
    *,
    profile: Profile,
    record: IntakeRecord,
    completeness: IntakeCompleteness,
    latest_user_message: str | None,
    transcript: tuple[TranscriptTurn, ...],
    is_opening: bool,
) -> list[ChatMessage]:
    if is_opening:
        return [
            ChatMessage(
                role=ChatRole.SYSTEM,
                content=(
                    "You are a compassionate intake therapist. "
                    f"Respond in {profile.primary_language}. "
                    "Generate a brief welcoming intake opening and ask one main question."
                ),
            ),
            ChatMessage(
                role=ChatRole.USER,
                content=f"Open the intake session for a patient named {profile.name}.",
            ),
        ]

    if completeness.complete:
        user_content = latest_user_message or "Close the intake session."
        return [
            ChatMessage(
                role=ChatRole.SYSTEM,
                content=(
                    "You are a compassionate intake therapist closing the intake. "
                    f"Respond in {profile.primary_language}. "
                    "Generate a brief closing that thanks the patient and explains "
                    "you have enough to move to the next step."
                ),
            ),
            ChatMessage(role=ChatRole.USER, content=user_content),
        ]

    recent = _recent_transcript(transcript, latest_user_message=latest_user_message)
    user_content = "\n\n".join(
        [
            f"Patient profile: {profile.name}, language={profile.primary_language}",
            f"Structured intake state:\n{_record_summary(record, completeness)}",
            f"Direct-ask instruction:\n{build_direct_ask_instruction(completeness.next_required_item)}",
            f"Recent transcript:\n{recent or 'None'}",
            f"Latest patient message:\n{latest_user_message or ''}",
        ]
    )
    return [
        ChatMessage(
            role=ChatRole.SYSTEM,
            content=(
                "You are a compassionate intake therapist. Respond in "
                f"{profile.primary_language}. Prioritize urgent safety or medical "
                "content before normal intake progression. Ask at most one main "
                "question. Do not expose internal field names."
            ),
        ),
        ChatMessage(role=ChatRole.USER, content=user_content),
    ]
