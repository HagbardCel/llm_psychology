"""Post-session prompt construction tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from jung.domain.models import Plan, Profile
from jung.phases.post_session.models import (
    InterventionEvidence,
    PostSessionInput,
    SessionAnalysisResult,
)
from jung.phases.post_session.prompts import (
    _ANALYSIS_EPISTEMIC_RULES,
    _UPDATE_EPISTEMIC_RULES,
    build_analysis_messages,
    build_update_messages,
)
from jung.phases.post_session.update_context import build_update_context_sections
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles


def _plan() -> Plan:
    now = datetime.now(UTC)
    return Plan(
        id=uuid4(),
        version=1,
        selected_style="cbt",
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=[],
        created_at=now,
    )


def _input() -> PostSessionInput:
    style = load_styles()["cbt"]
    return PostSessionInput(
        transcript=(
            TranscriptTurn(
                message_id=uuid4(),
                sequence=1,
                role="assistant",
                content="What feels unclear about your sleep?",
            ),
            TranscriptTurn(
                message_id=uuid4(),
                sequence=2,
                role="user",
                content="I slept badly.",
            ),
        ),
        current_plan=_plan(),
        profile=Profile(name="Alex", primary_language="English"),
        selected_style=style,
    )


def test_analysis_prompt_includes_style_instructions_and_sequences() -> None:
    messages = build_analysis_messages(_input())
    combined = "\n".join(message.content for message in messages)
    style = load_styles()["cbt"]
    assert style.post_session_instructions in combined
    assert "[sequence=1] assistant:" in combined
    assert "[sequence=2] user:" in combined
    assert "I slept badly." in combined
    assert _ANALYSIS_EPISTEMIC_RULES in combined


def test_update_prompt_omits_raw_transcript_and_includes_update_rules() -> None:
    analysis = SessionAnalysisResult(
        summary="Sleep difficulties explored.",
        key_themes=("sleep",),
    )
    messages = build_update_messages(_input(), analysis)
    combined = "\n".join(message.content for message in messages)
    assert "I slept badly." not in combined
    assert "Sleep difficulties explored." in combined
    assert _UPDATE_EPISTEMIC_RULES in combined
    assert "Do not regenerate the session summary" in combined


def test_update_context_preserves_complete_style_instructions() -> None:
    sections = build_update_context_sections(
        _input(),
        SessionAnalysisResult(summary="summary", key_themes=("sleep",)),
    )
    style_section = next(
        section
        for section in sections
        if section.startswith("Style reflection instructions:")
    )
    assert "Develop clear, measurable, and achievable treatment goals" in style_section
    assert not style_section.rstrip().endswith("...")


def test_update_context_includes_intervention_provenance() -> None:
    analysis = SessionAnalysisResult(
        summary="Sleep difficulties explored.",
        key_themes=("sleep",),
        intervention_evidence=(
            InterventionEvidence(
                intervention_description="Exploratory questioning",
                therapist_sequence=1,
                therapist_quote="What feels unclear about your sleep?",
                patient_sequence=2,
                patient_quote="I slept badly.",
            ),
        ),
    )
    sections = build_update_context_sections(_input(), analysis)
    analysis_section = next(
        section for section in sections if section.startswith("Session analysis:")
    )
    assert "therapist_sequence" in analysis_section
    assert "therapist_quote" in analysis_section
    assert "intervention_evidence" in analysis_section


def test_oversized_completed_transcript_retains_closing_material() -> None:
    turns = tuple(
        TranscriptTurn(
            message_id=uuid4(),
            sequence=index,
            role="user" if index % 2 else "assistant",
            content=(
                "MARKER_OLD " * 400
                if index == 1
                else "distant " * 300
                if index < 10
                else "closing insight about sleep"
            ),
        )
        for index in range(1, 11)
    )
    messages = build_analysis_messages(
        PostSessionInput(
            transcript=turns,
            current_plan=_plan(),
            profile=Profile(name="Alex", primary_language="English"),
            selected_style=load_styles()["cbt"],
        )
    )
    combined = "\n".join(message.content for message in messages)
    assert "closing insight about sleep" in combined
    assert "MARKER_OLD" not in combined
