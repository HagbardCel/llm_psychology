"""Post-session update context budgeting tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from jung.domain.grounding import GroundedPatientTurn
from jung.domain.models import Plan, Profile
from jung.phases.post_session.models import (
    InterventionEvidence,
    PostSessionInput,
    ResolvedSessionAnalysis,
    SessionAnalysisResult,
)
from jung.phases.post_session.update_context import (
    _UPDATE_CONTEXT_LIMIT,
    PostSessionUpdateContext,
    _section_payload_budget,
    build_update_context_document,
    build_update_context_sections,
)
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles


def _plan() -> Plan:
    now = datetime.now(UTC)
    return Plan(
        id=uuid4(),
        version=1,
        selected_style="cbt",
        focus="anxiety",
        themes=["worry", "sleep"],
        goals=["sleep better", "reduce worry"],
        current_progress="baseline",
        planned_interventions=["grounding", "thought record"],
        revision_recommendations=["review goals"],
        created_at=now,
    )


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


def test_update_context_stays_within_total_budget() -> None:
    sections = build_update_context_sections(_input(), _resolved())
    rendered = "\n\n".join(sections)
    assert rendered
    assert len(rendered) <= _UPDATE_CONTEXT_LIMIT


def test_section_payload_budget_accounts_for_heading_prefix() -> None:
    heading = "Session analysis"
    remaining = 100
    budget = _section_payload_budget(heading, remaining, remaining)
    assert budget == remaining - len(f"{heading}:\n")


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


def test_builder_rendered_output_never_exceeds_update_context_limit() -> None:
    message_id = uuid4()
    sections = build_update_context_sections(
        _input(
            prior_session_briefing={"summary": "b" * 5000},
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
    rendered = "\n\n".join(sections)
    assert len(rendered) <= _UPDATE_CONTEXT_LIMIT


def test_optional_sections_drop_before_plan_categories() -> None:
    sections = build_update_context_sections(
        _input(
            prior_session_briefing={"summary": "OPTIONAL_BRIEFING_MARKER" * 2000},
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
    rendered = "\n\n".join(sections)
    assert len(rendered) <= _UPDATE_CONTEXT_LIMIT
    assert not any(
        section.startswith("Recent session summaries:") for section in sections
    )
    plan_section = next(
        section for section in sections if section.startswith("Current plan:")
    )
    document = json.loads(plan_section.split(":\n", 1)[1])
    assert set(document) == {
        "focus",
        "themes",
        "goals",
        "current_progress",
        "planned_interventions",
        "revision_recommendations",
    }


def test_profile_context_projects_content_without_message_ids() -> None:
    message_id = str(uuid4())
    sections = build_update_context_sections(
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
    profile_section = next(
        section for section in sections if section.startswith("Derived profile:")
    )
    document = json.loads(profile_section.split(":\n", 1)[1])
    assert document == {
        "grounded_patient_turns": [{"source_sequence": 1, "content": "I slept badly."}],
        "grounded_patient_turns_omitted": 0,
    }
    assert message_id not in profile_section
    assert "legacy" not in profile_section


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
    sections = build_update_context_sections(
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
    analysis_section = next(
        section for section in sections if section.startswith("Session analysis:")
    )
    document = json.loads(analysis_section.split(":\n", 1)[1])
    assert "intervention_evidence" in document
    assert "intervention_evidence_omitted" in document
    assert "patient_turns" in document
    assert "patient_turns_omitted" in document
    assert document["intervention_evidence_omitted"] == 0
    assert document["patient_turns_omitted"] == 0
    assert "intervention_citations" not in document
    assert "patient_turn_citations" not in document
    assert document["intervention_evidence"][0]["status"] == "response_cited"
    assert document["patient_turns"][0]["content"] == "I slept badly."
    assert "source_message_id" not in document["patient_turns"][0]


def test_intentional_duplication_of_patient_content_retained_in_both_collections() -> (
    None
):
    shared = "I slept badly."
    sections = build_update_context_sections(
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
    analysis_section = next(
        section for section in sections if section.startswith("Session analysis:")
    )
    document = json.loads(analysis_section.split(":\n", 1)[1])
    assert document["intervention_evidence"][0]["patient_content"] == shared
    assert document["patient_turns"][0]["content"] == shared


def test_plan_section_retains_all_semantic_field_names() -> None:
    sections = build_update_context_sections(_input(), _resolved())
    plan_section = next(
        section for section in sections if section.startswith("Current plan:")
    )
    payload = plan_section.split(":\n", 1)[1]
    document = json.loads(payload)
    assert set(document) == {
        "focus",
        "themes",
        "goals",
        "current_progress",
        "planned_interventions",
        "revision_recommendations",
    }
    assert document["goals"]
    assert document["planned_interventions"]


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
    assert summaries == ["newest summary"]
    assert "old summary" not in summaries
    assert all("middle-too-large" not in item for item in summaries)


def test_serialized_sections_are_valid_json_or_prose() -> None:
    sections = build_update_context_sections(_input(), _resolved())
    for section in sections:
        if section.startswith("Session analysis:"):
            json.loads(section.split(":\n", 1)[1])
        if section.startswith("Current plan:") or section.startswith(
            "Derived profile:"
        ):
            json.loads(section.split(":\n", 1)[1])
        if section.startswith("Prior session briefing:"):
            assert not section.split(":\n", 1)[1].startswith("{")
