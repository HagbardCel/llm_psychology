"""Post-session update context budgeting tests against the runtime path."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.models import Message, MessageRole, Plan
from jung.domain.session_artifacts import (
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
)
from jung.llm.gateway import ChatRole
from jung.phases.context_projection import minimal_plan_projection
from jung.phases.post_session.models import (
    InterventionEvidence,
    PostSessionInput,
    ResolvedSessionAnalysis,
)
from jung.phases.post_session.prompts import build_update_messages
from jung.phases.post_session.update_context import (
    _UPDATE_USER_MESSAGE_LIMIT,
    PostSessionUpdateContext,
    build_update_user_message,
    enrich_analysis_without_evicting_evidence,
    intervention_payload,
)
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles


def _collect_object_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for item in value.values():
            keys.update(_collect_object_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_collect_object_keys(item))
    return keys


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


def _grounded_message(content: str, *, sequence: int = 1) -> Message:
    now = datetime.now(UTC)
    return Message(
        id=uuid4(),
        session_id=uuid4(),
        sequence=sequence,
        role=MessageRole.USER,
        content=content,
        client_message_id=uuid4(),
        created_at=now,
    )


def _briefing(**overrides: object) -> SessionBriefing:
    values: dict[str, object] = {
        "narrative_handoff": "Continue with sleep.",
        "recommended_opening_focus": "sleep readiness",
    }
    values.update(overrides)
    return SessionBriefing(**values)  # type: ignore[arg-type]


def _review(**briefing_overrides: object) -> SessionReview:
    briefing_values: dict[str, object] = {
        "narrative_handoff": "Continue with sleep.",
        "recommended_opening_focus": "sleep readiness",
    }
    briefing_values.update(briefing_overrides)
    return SessionReview(
        analysis=SessionAnalysis(
            summary="Prior session summary.",
            key_themes=("sleep",),
        ),
        briefing=SessionBriefing(**briefing_values),  # type: ignore[arg-type]
        plan_recommendation=PlanPatch(),
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
            TranscriptTurn(
                message_id=uuid4(),
                sequence=2,
                role="assistant",
                content="Tell me more.",
            ),
        ),
        "current_plan": _plan(),
        "selected_style": style,
    }
    values.update(overrides)
    return PostSessionInput(**values)


def _patient_turn(
    sequence: int,
    content: str,
    *,
    message_id=None,
) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=message_id or uuid4(),
        sequence=sequence,
        role="user",
        content=content,
    )


def _resolved(**overrides: object) -> ResolvedSessionAnalysis:
    analysis_overrides = {
        key: value
        for key, value in overrides.items()
        if key
        not in {
            "intervention_evidence",
            "selected_patient_turns",
        }
    }
    analysis_values: dict[str, object] = {
        "summary": "Sleep difficulties explored.",
        "key_themes": ("sleep", "worry"),
    }
    analysis_values.update(analysis_overrides)
    return ResolvedSessionAnalysis(
        analysis=SessionAnalysis(**analysis_values),  # type: ignore[arg-type]
        intervention_evidence=overrides.get("intervention_evidence", ()),  # type: ignore[arg-type]
        selected_patient_turns=overrides.get("selected_patient_turns", ()),  # type: ignore[arg-type]
    )


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
    selected = _patient_turn(1, "I slept badly.")
    context = PostSessionUpdateContext.from_resolved(
        _resolved(
            summary="summary",
            key_themes=("sleep",),
            intervention_evidence=(evidence,),
            selected_patient_turns=(selected,),
        )
    )
    assert context.intervention_evidence == (evidence,)
    assert context.selected_patient_turns == (selected,)
    assert context.summary == "summary"


def test_intervention_payload_derives_status_for_prompt_projection() -> None:
    cited = InterventionEvidence(
        intervention_description="Exploratory questioning",
        therapist_sequence=2,
        therapist_content="What feels unclear?",
        patient_sequence=3,
        patient_content="I kept waking up.",
    )
    delivered = InterventionEvidence(
        intervention_description="Exploratory questioning",
        therapist_sequence=2,
        therapist_content="What feels unclear?",
    )
    assert intervention_payload(cited)["status"] == "response_cited"
    assert intervention_payload(delivered)["status"] == "delivered"
    assert "status" not in cited.model_dump(mode="json")


def test_builder_rendered_output_never_exceeds_update_limit() -> None:
    message = build_update_user_message(
        _input(
            prior_reviews=(_review(narrative_handoff="b" * 5000),),
            grounded_patient_messages=(_grounded_message("p" * 5000),),
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
            prior_reviews=(
                _review(
                    narrative_handoff="OPTIONAL_BRIEFING_MARKER" * 200,
                ),
            ),
            grounded_patient_messages=(_grounded_message("p" * 5000),),
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
            selected_patient_turns=tuple(
                _patient_turn(index + 1, "p" * 400) for index in range(20)
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
    assert "validated_session_analysis" in document
    assert "summary" in document["validated_session_analysis"]
    assert "transcript" not in document


def test_profile_context_projects_content_without_message_ids() -> None:
    message = _grounded_message("I slept badly.")
    document = build_update_context_document(
        _input(grounded_patient_messages=(message,)),
        _resolved(),
    )
    longitudinal = document["longitudinal_context"]
    assert longitudinal["grounded_patient_turns"] == [{"content": "I slept badly."}]
    rendered = json.dumps(longitudinal)
    assert str(message.id) not in rendered


def test_update_document_has_no_uuids_in_profile_projection() -> None:
    message = _grounded_message("I do not think I want to die.", sequence=2)
    document = build_update_context_document(
        _input(grounded_patient_messages=(message,)),
        _resolved(selected_patient_turns=(_patient_turn(2, message.content),)),
    )
    longitudinal = document["longitudinal_context"]
    rendered = json.dumps(longitudinal)
    assert str(message.id) not in rendered
    assert longitudinal["grounded_patient_turns"][0]["content"] == (
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
            selected_patient_turns=(_patient_turn(2, "I slept badly."),),
        ),
    )
    analysis = document["validated_session_analysis"]
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
            selected_patient_turns=tuple(
                _patient_turn(index + 1, "p" * 2000) for index in range(5)
            ),
        ),
    )
    analysis = document["validated_session_analysis"]
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
            selected_patient_turns=(_patient_turn(2, shared),),
        ),
    )
    analysis = document["validated_session_analysis"]
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


def test_prior_briefing_handoff_complete_or_omit() -> None:
    negation = "I am not ready to do that."
    document = build_update_context_document(
        _input(
            prior_reviews=(
                _review(
                    narrative_handoff=negation,
                    continuity_points=(negation,),
                ),
            )
        ),
        _resolved(),
    )
    if "longitudinal_context" in document:
        briefing = document["longitudinal_context"].get("latest_supervisor_briefing")
        if briefing is not None:
            assert "intervention_evidence" not in briefing
            assert negation in briefing["narrative_handoff"]
            assert "..." not in briefing["narrative_handoff"]


def test_patient_name_absent_from_update_prompt() -> None:
    messages = build_update_messages(_input(), _resolved())
    user = next(m.content for m in messages if m.role == ChatRole.USER)
    system = next(m.content for m in messages if m.role == ChatRole.SYSTEM)
    assert "Alex" not in user
    assert "Alex" not in system
    assert '"patient"' not in user.split("</context_data>")[0]


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


def test_update_system_instructions_name_validated_analysis_authority() -> None:
    messages = build_update_messages(_input(), _resolved())
    system = next(m.content for m in messages if m.role == ChatRole.SYSTEM)
    assert "validated_session_analysis" in system
    assert "authoritative account of the just-completed session" in system
    assert "completed_session.transcript" not in system


def test_interpretive_analysis_outranks_plan_richness_in_update_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interpretive analysis is frozen before optional plan richness in the builder."""
    import jung.phases.post_session.update_context as update_context
    from jung.llm.prompt_context import rendered_context_user_message_length

    def dynamic_fits(
        document: dict[str, object],
        *,
        task: str = update_context._UPDATE_TASK,
        limit: int | None = None,
    ) -> bool:
        effective_limit = (
            update_context._UPDATE_USER_MESSAGE_LIMIT if limit is None else limit
        )
        return (
            rendered_context_user_message_length(document, task=task) <= effective_limit
        )

    monkeypatch.setattr(update_context, "_fits_update", dynamic_fits)

    rich_plan = _plan(
        focus="focus",
        themes=tuple(f"theme-{index}-" * 30 for index in range(8)),
        goals=tuple(f"goal-{index}-" * 30 for index in range(8)),
        planned_interventions=tuple(f"iv-{index}-" * 30 for index in range(8)),
        revision_recommendations=tuple(f"rev-{index}-" * 30 for index in range(8)),
        current_progress="progress",
    )
    input = _input(current_plan=rich_plan)
    resolved = _resolved(
        summary="Sleep difficulties explored with detail.",
        key_themes=tuple(f"CURRENT-THEME-{index}-" * 40 for index in range(18)),
        dominant_affects=tuple(f"affect-{index}-" * 40 for index in range(15)),
        important_moments=tuple(f"moment-{index}-" * 40 for index in range(15)),
        patient_insights=tuple(f"insight-{index}-" * 40 for index in range(15)),
        progress_indicators=tuple(f"progress-{index}-" * 40 for index in range(15)),
        unresolved_topics=tuple(f"topic-{index}-" * 40 for index in range(15)),
        safety_or_boundary_notes=tuple(f"note-{index}-" * 40 for index in range(10)),
    )

    monkeypatch.setattr(update_context, "_UPDATE_USER_MESSAGE_LIMIT", 100_000)
    full_document = build_update_context_document(input, resolved)
    full_analysis = full_document["validated_session_analysis"]
    minimal_plan = minimal_plan_projection(rich_plan)
    task = update_context._UPDATE_TASK

    len_minimal = rendered_context_user_message_length(
        {
            "current_plan": minimal_plan,
            "validated_session_analysis": full_analysis,
        },
        task=task,
    )
    len_rich = rendered_context_user_message_length(
        {
            "current_plan": full_document["current_plan"],
            "validated_session_analysis": full_analysis,
        },
        task=task,
    )
    baseline_analysis = {
        key: full_analysis[key]
        for key in (
            "summary",
            "intervention_evidence",
            "intervention_evidence_omitted",
            "patient_turns",
            "patient_turns_omitted",
        )
    }
    len_wrong_order_rich = rendered_context_user_message_length(
        {
            "current_plan": full_document["current_plan"],
            "validated_session_analysis": baseline_analysis,
        },
        task=task,
    )

    assert len_minimal < len_rich
    assert len_wrong_order_rich <= len_minimal
    assert len_rich > len_minimal

    monkeypatch.setattr(update_context, "_UPDATE_USER_MESSAGE_LIMIT", len_minimal)
    tight_document = build_update_context_document(input, resolved)

    assert tight_document["validated_session_analysis"] == full_analysis
    assert tight_document["current_plan"] == minimal_plan


def test_forbidden_prompt_keys_absent_from_update_document() -> None:
    document = build_update_context_document(_input(), _resolved())
    keys = _collect_object_keys(document)
    forbidden = {
        "derived_profile",
        "recent_session_summaries",
        "prior_session_briefing",
        "session_briefing",
        "session_analysis",
    }
    assert forbidden.isdisjoint(keys)
