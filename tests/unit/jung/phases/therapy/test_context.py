"""Therapy context budgeting tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.models import Plan, Profile
from jung.llm.gateway import ChatRole
from jung.phases.therapy.context import (
    _SECTION_SEPARATOR,
    build_context_sections,
    build_opening_context_sections,
)
from jung.phases.therapy.models import TherapyContextLimits, TherapyTurnInput
from jung.phases.therapy.prompts import UNTRUSTED_DATA_RULE, build_messages
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


def _turn(sequence: int, role: str, content: str) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=uuid4(),
        sequence=sequence,
        role=role,
        content=content,
    )


def _input(**overrides: object) -> TherapyTurnInput:
    values: dict[str, object] = {
        "profile": Profile(name="Alex", primary_language="English"),
        "current_plan": _plan(),
        "selected_style": load_styles()["cbt"],
        "context_limits": TherapyContextLimits(
            max_transcript_turns=6,
            max_section_chars=200,
            max_total_chars=1000,
        ),
    }
    values.update(overrides)
    return TherapyTurnInput(**values)


def test_current_message_preserved_under_tight_budget() -> None:
    huge = "x" * 5000
    sections = build_context_sections(
        _input(
            latest_user_message=huge,
            transcript=(
                _turn(1, "assistant", "hello"),
                _turn(2, "user", huge),
            ),
        )
    )
    combined = "\n".join(sections)
    assert huge in combined
    assert combined.count(huge) == 1


def test_message_exceeding_total_budget_still_present() -> None:
    message = "y" * 2000
    sections = build_context_sections(
        _input(
            latest_user_message=message,
            transcript=(_turn(1, "user", message),),
            context_limits=TherapyContextLimits(
                max_transcript_turns=6,
                max_section_chars=200,
                max_total_chars=1000,
            ),
            session_briefing={
                "narrative_handoff": "x" * 5000,
                "intervention_evidence": [],
            },
            derived_profile={
                "grounded_patient_turns": [
                    {
                        "source_message_id": str(uuid4()),
                        "source_sequence": 1,
                        "content": "y" * 5000,
                    }
                ]
            },
            recent_session_summaries=("z" * 5000,),
        )
    )
    combined = "\n".join(sections)
    assert message in combined
    assert combined.count(message) == 1
    assert "x" * 5000 not in combined
    assert "y" * 5000 not in combined
    assert "z" * 5000 not in combined


def test_transcript_dedupe_keeps_earlier_identical_user_turn() -> None:
    duplicate = "I feel anxious"
    sections = build_context_sections(
        _input(
            latest_user_message=duplicate,
            transcript=(
                _turn(1, "user", duplicate),
                _turn(2, "assistant", "Tell me more."),
                _turn(3, "user", duplicate),
            ),
        )
    )
    combined = "\n".join(sections)
    assert combined.count(duplicate) == 2
    assert "user: I feel anxious" in combined
    assert "Current patient message:\nI feel anxious" in combined


def test_opening_context_respects_total_budget() -> None:
    sections = build_opening_context_sections(
        _input(
            is_opening_turn=True,
            session_briefing={
                "narrative_handoff": "b" * 5000,
                "intervention_evidence": [],
            },
            derived_profile={},
            recent_session_summaries=("s" * 5000,),
            context_limits=TherapyContextLimits(
                max_transcript_turns=6,
                max_section_chars=2500,
                max_total_chars=1000,
            ),
            selected_style=load_styles()["cbt"],
        )
    )
    compressible = [
        section for section in sections if not section.startswith("Patient:")
    ]
    rendered = _SECTION_SEPARATOR.join(compressible)
    plan_section = next(
        section for section in compressible if section.startswith("Current plan:")
    )
    assert plan_section.split(":\n", 1)[1].strip()
    assert not any(
        section.startswith("Therapy style instructions:") for section in compressible
    )
    assert len(rendered) <= 1000


def test_style_instructions_live_in_system_message() -> None:
    style = load_styles()["cbt"]
    messages = build_messages(
        _input(
            latest_user_message="I slept badly.",
            transcript=(_turn(1, "user", "I slept badly."),),
        )
    )
    system_text = "\n".join(m.content for m in messages if m.role == ChatRole.SYSTEM)
    user_text = "\n".join(m.content for m in messages if m.role == ChatRole.USER)
    assert style.therapist_instructions in system_text
    assert style.therapist_instructions not in user_text
    assert UNTRUSTED_DATA_RULE in system_text
    assert "I slept badly." in user_text
    assert "I slept badly." not in system_text
    assert _plan().focus in user_text


def test_briefing_evidence_not_truncated_in_final_context() -> None:
    content = "I am not recommending that you confront them immediately."
    briefing = {
        "narrative_handoff": "Session focused on readiness.",
        "recommended_opening_focus": "pace",
        "intervention_evidence": [
            {
                "intervention_description": "Pacing",
                "status": "response_cited",
                "therapist_sequence": 2,
                "therapist_content": content,
                "patient_sequence": 3,
                "patient_content": "I am not ready to do that.",
            }
        ],
    }
    sections = build_opening_context_sections(
        _input(
            is_opening_turn=True,
            session_briefing=briefing,
            context_limits=TherapyContextLimits(
                max_transcript_turns=6,
                max_section_chars=5000,
                max_total_chars=8000,
            ),
        )
    )
    combined = "\n".join(sections)
    assert content in combined
    assert "I am not ready to do that." in combined
    assert "..." not in combined.split("Session briefing:")[-1].split("\n\n")[0]


def test_grounded_profile_allowlist_excludes_legacy_keys() -> None:
    message_id = uuid4()
    sections = build_opening_context_sections(
        _input(
            is_opening_turn=True,
            derived_profile={
                "hypotheses": ["should never appear"],
                "observations": ["legacy"],
                "patient_stated_facts": ["legacy fact"],
                "grounded_patient_turns": [
                    {
                        "source_message_id": str(message_id),
                        "source_sequence": 1,
                        "content": "I do not think I want to die.",
                    }
                ],
            },
            context_limits=TherapyContextLimits(
                max_transcript_turns=6,
                max_section_chars=5000,
                max_total_chars=8000,
            ),
        )
    )
    combined = "\n".join(sections)
    assert "I do not think I want to die." in combined
    assert "should never appear" not in combined
    assert "legacy fact" not in combined
    assert str(message_id) not in combined


def test_malformed_grounded_profile_raises() -> None:
    with pytest.raises(ValueError, match="grounded_patient_turns must be a list"):
        build_opening_context_sections(
            _input(
                is_opening_turn=True,
                derived_profile={"grounded_patient_turns": None},
            )
        )


def test_opening_context_includes_session_briefing() -> None:
    briefing = {
        "narrative_handoff": "prior sleep focus",
        "recommended_opening_focus": "sleep",
        "intervention_evidence": [],
    }
    sections = build_opening_context_sections(
        _input(is_opening_turn=True, session_briefing=briefing),
    )
    combined = "\n".join(sections)
    assert "prior sleep focus" in combined
    assert "Session briefing:" in combined


def test_oversized_transcript_retains_final_exchange() -> None:
    sections = build_context_sections(
        _input(
            latest_user_message="brand new answer",
            transcript=(
                _turn(1, "user", "old " * 500),
                _turn(2, "assistant", "middle " * 500),
                _turn(3, "user", "brand new answer"),
            ),
            context_limits=TherapyContextLimits(
                max_transcript_turns=6,
                max_section_chars=200,
                max_total_chars=1000,
            ),
        )
    )
    combined = "\n".join(sections)
    assert "brand new answer" in combined
