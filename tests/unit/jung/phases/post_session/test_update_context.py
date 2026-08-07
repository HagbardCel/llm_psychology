"""Post-session update context budgeting tests against the runtime path."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.grounding import GroundedPatientTurn
from jung.domain.models import Plan, Profile
from jung.llm.gateway import ChatRole
from jung.phases.post_session.models import (
    InterventionEvidence,
    PostSessionInput,
    ResolvedSessionAnalysis,
    SessionAnalysisResult,
)
from jung.phases.post_session.prompts import build_update_messages
from jung.phases.post_session.update_context import (
    _UPDATE_USER_MESSAGE_LIMIT,
    PostSessionUpdateContext,
    build_update_user_message,
    enrich_analysis_without_evicting_evidence,
)
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles


def _parse_update_context_document(message: str) -> dict[str, object]:
    import re

    match = re.search(
        r"<context_data>\n(.*)\n</context_data>",
        message,
        flags=re.DOTALL,
    )
    if match is None:
        raise ValueError("update user message missing context_data block")
    return json.loads(match.group(1))


def build_update_context_document(
    input: PostSessionInput,
    resolved: ResolvedSessionAnalysis,
) -> dict[str, object]:
    return _parse_update_context_document(build_update_user_message(input, resolved))


def _plan(**overrides: object) -> Plan:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "id": uuid4(),
        "version": 1,
        "selected_style": "cbt",
        "focus": "anxiety",
        "themes": ["worry", "sleep"],
        "goals": ["sleep better", "reduce worry"],
        "current_progress": "baseline",
        "planned_interventions": ["grounding", "thought record"],
        "revision_recommendations": ["review goals"],
        "created_at": now,
    }
    values.update(overrides)
    return Plan(**values)  # type: ignore[arg-type]


def _input(**overrides: object) -> PostSessionInput:
    style = load_styles()["cbt"]
    values: dict[str, object] = {
        "transcript": (
            TranscriptTurn(
                message_id=uuid4(),
                sequence=1,
                role="user",
                content="I slept badly.",
            ),
            TranscriptTurn(
                message_id=uuid4(),
                sequence=2,
                role="assistant",
                content="Tell me more.",
            ),
        ),
        "current_plan": _plan(),
        "profile": Profile(name="Alex", primary_language="English"),
        "selected_style": style,
    }
    values.update(overrides)
    return PostSessionInput(**values)


def _resolved(**overrides: object) -> ResolvedSessionAnalysis:
    analysis_overrides = {
        key: value
        for key, value in overrides.items()
        if key
        not in {
            "intervention_evidence",
            "grounded_patient_turns",
        }
    }
    analysis_values: dict[str, object] = {
        "summary": "Sleep difficulties explored.",
        "key_themes": ("sleep", "worry"),
    }
    analysis_values.update(analysis_overrides)
    return ResolvedSessionAnalysis(
        analysis=SessionAnalysisResult(**analysis_values),  # type: ignore[arg-type]
        intervention_evidence=overrides.get("intervention_evidence", ()),  # type: ignore[arg-type]
        grounded_patient_turns=overrides.get("grounded_patient_turns", ()),  # type: ignore[arg-type]
    )


def _briefing(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "narrative_handoff": "Continue with sleep.",
        "recommended_opening_focus": "sleep readiness",
        "intervention_evidence": [],
    }
    values.update(overrides)
    return values


def test_update_user_message_stays_within_total_budget() -> None:
    message = build_update_user_message(_input(), _resolved())
    assert message
    assert len(message) <= _UPDATE_USER_MESSAGE_LIMIT
    assert "<context_data>" in message
    assert "Produce the next-session briefing draft and plan patch." in message
    assert message.index("</context_data>") < message.index(
        "Produce the next-session briefing draft"
    )


def test_from_resolved_projects_evidence_not_provider_citations() -> None:
    evidence = InterventionEvidence(
        intervention_description="Exploratory questioning",
        therapist_sequence=2,
        therapist_content="What feels unclear?",
        patient_sequence=3,
        patient_content="I kept waking up.",
    )
    grounded = GroundedPatientTurn(
        source_message_id=uuid4(),
        source_sequence=1,
        content="I slept badly.",
    )
    context = PostSessionUpdateContext.from_resolved(
        _resolved(
            summary="summary",
            key_themes=("sleep",),
            intervention_evidence=(evidence,),
            grounded_patient_turns=(grounded,),
        )
    )
    assert context.intervention_evidence == (evidence,)
    assert context.patient_turns == (grounded,)
    assert context.summary == "summary"


def test_builder_rendered_output_never_exceeds_update_limit() -> None:
    message_id = uuid4()
    message = build_update_user_message(
        _input(
            prior_session_briefing=_briefing(narrative_handoff="b" * 5000),
            recent_session_summaries=tuple(
                f"summary-{index}" * 200 for index in range(20)
            ),
            derived_profile={
                "grounded_patient_turns": [
                    {
                        "source_message_id": str(message_id),
                        "source_sequence": 1,
                        "content": "p" * 5000,
                    }
                ]
            },
        ),
        _resolved(
            summary="x" * 5000,
            key_themes=tuple(f"theme-{index}" for index in range(50)),
        ),
    )
    assert len(message) <= _UPDATE_USER_MESSAGE_LIMIT


def test_optional_sections_drop_before_plan_and_analysis() -> None:
    document = build_update_context_document(
        _input(
            prior_session_briefing=_briefing(
                narrative_handoff="OPTIONAL_BRIEFING_MARKER" * 200,
                intervention_evidence=[
                    {
                        "intervention_description": "Pacing",
                        "therapist_sequence": 2,
                        "therapist_content": "I am not ready to do that. " * 40,
                        "patient_sequence": 3,
                        "patient_content": "I am not ready to do that.",
                    }
                ],
            ),
            recent_session_summaries=("old " * 2000, "new " * 2000),
            derived_profile={
                "grounded_patient_turns": [
                    {
                        "source_message_id": str(uuid4()),
                        "source_sequence": 1,
                        "content": "p" * 5000,
                    }
                ]
            },
        ),
        _resolved(
            summary="x" * 10000,
            key_themes=tuple(f"theme-{index}" * 20 for index in range(80)),
            intervention_evidence=tuple(
                InterventionEvidence(
                    intervention_description=f"intervention-{index}",
                    therapist_sequence=index + 1,
                    therapist_content="t" * 400,
                )
                for index in range(20)
            ),
            grounded_patient_turns=tuple(
                GroundedPatientTurn(
                    source_message_id=uuid4(),
                    source_sequence=index + 1,
                    content="p" * 400,
                )
                for index in range(20)
            ),
        ),
    )
    assert "current_plan" in document
    assert set(document["current_plan"]) == {
        "focus",
        "themes",
        "goals",
        "current_progress",
        "planned_interventions",
        "revision_recommendations",
    }
    assert "session_analysis" in document
    assert "summary" in document["session_analysis"]
    assert "transcript" not in document


def test_profile_context_projects_content_without_message_ids() -> None:
    message_id = str(uuid4())
    document = build_update_context_document(
        _input(
            derived_profile={
                "grounded_patient_turns": [
                    {
                        "source_message_id": message_id,
                        "source_sequence": 1,
                        "content": "I slept badly.",
                    }
                ],
                "hypotheses": ["legacy hypothesis"],
                "observations": ["legacy observation"],
                "patient_stated_facts": ["legacy fact"],
            }
        ),
        _resolved(),
    )
    profile = document["derived_profile"]
    assert profile == {
        "grounded_patient_turns": [{"content": "I slept badly."}],
        "grounded_patient_turns_omitted": 0,
    }
    rendered = json.dumps(profile)
    assert message_id not in rendered
    assert "legacy" not in rendered


def test_update_document_has_no_uuids_in_profile_projection() -> None:
    message_id = uuid4()
    document = build_update_context_document(
        _input(
            derived_profile={
                "grounded_patient_turns": [
                    {
                        "source_message_id": str(message_id),
                        "source_sequence": 2,
                        "content": "I do not think I want to die.",
                    }
                ]
            }
        ),
        _resolved(
            grounded_patient_turns=(
                GroundedPatientTurn(
                    source_message_id=message_id,
                    source_sequence=2,
                    content="I do not think I want to die.",
                ),
            )
        ),
    )
    profile = document["derived_profile"]
    assert isinstance(profile, dict)
    rendered = json.dumps(profile)
    assert str(message_id) not in rendered
    assert profile["grounded_patient_turns"][0]["content"] == (
        "I do not think I want to die."
    )


def test_analysis_document_emits_omission_markers_and_resolved_evidence() -> None:
    document = build_update_context_document(
        _input(),
        _resolved(
            intervention_evidence=(
                InterventionEvidence(
                    intervention_description="Exploratory questioning",
                    therapist_sequence=1,
                    therapist_content="What feels unclear about your sleep?",
                    patient_sequence=2,
                    patient_content="I slept badly.",
                ),
            ),
            grounded_patient_turns=(
                GroundedPatientTurn(
                    source_message_id=uuid4(),
                    source_sequence=2,
                    content="I slept badly.",
                ),
            ),
        ),
    )
    analysis = document["session_analysis"]
    assert "intervention_evidence" in analysis
    assert "intervention_evidence_omitted" in analysis
    assert "patient_turns" in analysis
    assert "patient_turns_omitted" in analysis
    assert analysis["intervention_evidence_omitted"] == 0
    assert analysis["patient_turns_omitted"] == 0
    assert "intervention_citations" not in analysis
    assert "patient_turn_citations" not in analysis
    assert analysis["intervention_evidence"][0]["status"] == "response_cited"
    assert analysis["patient_turns"][0]["content"] == "I slept badly."
    assert "source_message_id" not in analysis["patient_turns"][0]


def test_all_omitted_evidence_reports_source_totals() -> None:
    document = build_update_context_document(
        _input(),
        _resolved(
            summary="x" * 200,
            intervention_evidence=tuple(
                InterventionEvidence(
                    intervention_description=f"intervention-{index}",
                    therapist_sequence=index + 1,
                    therapist_content="t" * 2000,
                )
                for index in range(5)
            ),
            grounded_patient_turns=tuple(
                GroundedPatientTurn(
                    source_message_id=uuid4(),
                    source_sequence=index + 1,
                    content="p" * 2000,
                )
                for index in range(5)
            ),
        ),
    )
    analysis = document["session_analysis"]
    assert (
        analysis["intervention_evidence_omitted"]
        + len(analysis["intervention_evidence"])
        == 5
    )
    assert analysis["patient_turns_omitted"] + len(analysis["patient_turns"]) == 5


def test_intentional_duplication_of_patient_content_retained_in_both_collections() -> (
    None
):
    shared = "I slept badly."
    document = build_update_context_document(
        _input(),
        _resolved(
            intervention_evidence=(
                InterventionEvidence(
                    intervention_description="Exploratory questioning",
                    therapist_sequence=1,
                    therapist_content="What feels unclear?",
                    patient_sequence=2,
                    patient_content=shared,
                ),
            ),
            grounded_patient_turns=(
                GroundedPatientTurn(
                    source_message_id=uuid4(),
                    source_sequence=2,
                    content=shared,
                ),
            ),
        ),
    )
    analysis = document["session_analysis"]
    assert analysis["intervention_evidence"][0]["patient_content"] == shared
    assert analysis["patient_turns"][0]["content"] == shared


def test_plan_section_retains_all_semantic_field_names() -> None:
    document = build_update_context_document(_input(), _resolved())
    plan = document["current_plan"]
    assert set(plan) == {
        "focus",
        "themes",
        "goals",
        "current_progress",
        "planned_interventions",
        "revision_recommendations",
    }
    assert plan["goals"]
    assert plan["planned_interventions"]


def test_newest_summaries_preferred() -> None:
    document = build_update_context_document(
        _input(
            recent_session_summaries=(
                "old summary",
                "middle-too-large " * 400,
                "newest summary",
            )
        ),
        _resolved(),
    )
    summaries = document["recent_session_summaries"]
    assert summaries[0] == "newest summary" or "newest summary" in summaries
    assert "newest summary" in summaries


def test_prior_briefing_evidence_complete_or_omit() -> None:
    negation = "I am not ready to do that."
    document = build_update_context_document(
        _input(
            prior_session_briefing=_briefing(
                intervention_evidence=[
                    {
                        "intervention_description": "Pacing",
                        "therapist_sequence": 2,
                        "therapist_content": "Shall we try that?",
                        "patient_sequence": 3,
                        "patient_content": negation,
                    }
                ]
            )
        ),
        _resolved(),
    )
    briefing = document["prior_session_briefing"]
    evidence = briefing["intervention_evidence"]
    if evidence:
        assert evidence[0]["patient_content"] == negation
        assert "..." not in evidence[0]["patient_content"]
    else:
        assert briefing["intervention_evidence_omitted"] == 1


def test_patient_name_absent_from_update_prompt() -> None:
    messages = build_update_messages(_input(), _resolved())
    user = next(m.content for m in messages if m.role == ChatRole.USER)
    system = next(m.content for m in messages if m.role == ChatRole.SYSTEM)
    assert "Alex" not in user
    assert "Alex" not in system
    assert '"patient"' not in user.split("</context_data>")[0]


def test_no_legacy_section_builder_imports() -> None:
    import jung.phases.post_session.update_context as update_context

    assert not hasattr(update_context, "build_update_context_sections")
    assert not hasattr(update_context, "_briefing_prose")


def test_enrich_analysis_rejects_reserved_keys() -> None:
    baseline = {
        "summary": "stable summary",
        "intervention_evidence": [{"therapist_sequence": 1}],
        "intervention_evidence_omitted": 0,
        "patient_turns": [{"source_sequence": 2}],
        "patient_turns_omitted": 0,
    }
    with pytest.raises(ValueError, match="reserved fields"):
        enrich_analysis_without_evicting_evidence(
            baseline,
            interpretive_candidates=(
                {
                    "key_themes": ["sleep"],
                    "intervention_evidence": [],
                },
            ),
            fits=lambda _doc: True,
        )


def test_enrich_analysis_does_not_evict_evidence_for_rich_interpretation() -> None:
    baseline = {
        "summary": "stable summary",
        "intervention_evidence": [{"id": "a"}, {"id": "b"}],
        "intervention_evidence_omitted": 0,
        "patient_turns": [{"id": "p1"}, {"id": "p2"}],
        "patient_turns_omitted": 0,
    }
    rich = {
        "key_themes": ["a", "b", "c"],
        "dominant_affects": ["worry"],
    }

    def fits(document: dict[str, object]) -> bool:
        evidence = document["intervention_evidence"]
        themes = document.get("key_themes", [])
        assert isinstance(evidence, list)
        assert isinstance(themes, list)
        # Rich interpretation (3+ themes) cannot coexist with both evidence atoms.
        if len(themes) >= 3 and len(evidence) >= 2:
            return False
        return True

    result = enrich_analysis_without_evicting_evidence(
        baseline,
        interpretive_candidates=(rich, {"key_themes": ["a"]}),
        fits=fits,
    )
    assert result["intervention_evidence"] == baseline["intervention_evidence"]
    assert result["patient_turns"] == baseline["patient_turns"]
    assert result["intervention_evidence_omitted"] == 0
    assert result["patient_turns_omitted"] == 0
    assert result["summary"] == "stable summary"
    assert result["key_themes"] == ["a"]


def test_rich_plan_does_not_starve_evidence() -> None:
    from jung.phases.context_projection import (
        enrich_plan_projection,
        minimal_plan_projection,
    )

    plan = _plan(
        focus="x" * 200,
        themes=tuple(f"theme-{i}" for i in range(10)),
        goals=tuple(f"goal-{i}" for i in range(10)),
        planned_interventions=tuple(f"iv-{i}" for i in range(10)),
        revision_recommendations=tuple(f"rev-{i}" for i in range(10)),
        current_progress="y" * 200,
    )
    minimal = minimal_plan_projection(plan)
    evidence = {
        "summary": "summary",
        "intervention_evidence": [{"id": "a"}, {"id": "b"}],
        "intervention_evidence_omitted": 0,
        "patient_turns": [],
        "patient_turns_omitted": 0,
    }

    def fits(plan_doc: dict[str, object]) -> bool:
        themes = plan_doc.get("themes", [])
        assert isinstance(themes, list)
        # Rich plan (any themes retained) cannot coexist with two evidence atoms.
        if themes and len(evidence["intervention_evidence"]) >= 2:
            return False
        return True

    enriched_plan = enrich_plan_projection(plan, baseline=minimal, fits=fits)
    assert enriched_plan["themes"] == []
    assert set(enriched_plan) == {
        "focus",
        "themes",
        "goals",
        "current_progress",
        "planned_interventions",
        "revision_recommendations",
    }


def test_update_builder_stays_within_limit_and_keeps_plan_keys() -> None:
    document = build_update_context_document(_input(), _resolved())
    message = build_update_user_message(_input(), _resolved())
    assert len(message) <= _UPDATE_USER_MESSAGE_LIMIT
    assert set(document["current_plan"]) == {
        "focus",
        "themes",
        "goals",
        "current_progress",
        "planned_interventions",
        "revision_recommendations",
    }
