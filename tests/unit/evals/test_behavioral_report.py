"""Deterministic tests for behavioral report scenarios and helpers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from pydantic import BaseModel

from evals import behavioral_report
from evals.harness import eval_plan, next_plan_after_review
from evals.scenarios import (
    ASSESSMENT_SCENARIOS,
    ATTRIBUTION_SCENARIO,
    BEHAVIORAL_SCENARIOS,
    LANGUAGE_SCENARIOS,
    LONGITUDINAL_SUPERVISOR_SCENARIOS,
    SAFETY_STYLE_IDS,
    STYLE_COMPARISONS,
)
from jung.domain.session_artifacts import (
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
)
from jung.domain.text import normalize_content
from jung.llm.gateway import StructuredOutputMode
from jung.phases.intake.completion import intake_record_completion_decision
from jung.phases.intake.models import IntakeEvidence
from tests.support.local_llm import LocalModelEnvironment


def _iter_evidence(value: object) -> Iterator[IntakeEvidence]:
    if isinstance(value, IntakeEvidence):
        yield value
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_evidence(item)
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            yield from _iter_evidence(getattr(value, field_name))


def _review(*, focus: str | None) -> SessionReview:
    return SessionReview(
        analysis=SessionAnalysis(
            summary="Session summary.",
            key_themes=("anxiety",),
        ),
        briefing=SessionBriefing(
            narrative_handoff="Continue carefully.",
            recommended_opening_focus="Check in.",
        ),
        plan_recommendation=PlanPatch(focus=focus),
    )


def test_scenario_inventory_counts() -> None:
    assert len(BEHAVIORAL_SCENARIOS) == 6
    assert SAFETY_STYLE_IDS == ("cbt", "jung", "freud")
    assert len(STYLE_COMPARISONS) == 3
    assert len(ASSESSMENT_SCENARIOS) == 4
    assert len(LANGUAGE_SCENARIOS) == 3
    assert len(LONGITUDINAL_SUPERVISOR_SCENARIOS) == 4
    assert ATTRIBUTION_SCENARIO.key == "historical_current_separation"
    keys = {scenario.key for scenario in LONGITUDINAL_SUPERVISOR_SCENARIOS}
    assert keys == {
        "genuine_progress",
        "failed_intervention",
        "changed_priority",
        "noop_revision",
    }


def test_assessment_scenarios_are_production_reachable() -> None:
    for scenario in ASSESSMENT_SCENARIOS:
        transcript = scenario.transcript()
        patient_turn_count = sum(turn.role == "user" for turn in transcript)
        assert patient_turn_count == 3
        record = scenario.intake_record()
        assert intake_record_completion_decision(
            record,
            patient_turn_count=patient_turn_count,
        ).complete
        by_sequence = {turn.sequence: turn for turn in transcript}
        for evidence in _iter_evidence(record):
            if not evidence.is_present():
                continue
            assert evidence.source_role == "user"
            assert evidence.source_message_sequence is not None
            assert evidence.evidence_quote is not None
            source = by_sequence[evidence.source_message_sequence]
            assert source.role == "user"
            assert normalize_content(evidence.evidence_quote).casefold() in (
                normalize_content(source.content).casefold()
            )


def test_next_plan_after_review_noop_reuses_plan() -> None:
    plan = eval_plan("cbt")
    review = _review(focus=None)
    next_plan = next_plan_after_review(plan, review)
    assert next_plan is plan
    assert next_plan.version == plan.version
    assert next_plan.id == plan.id


def test_next_plan_after_review_changed_patch_bumps_version() -> None:
    plan = eval_plan("cbt")
    review = _review(focus="new priority after conflict")
    next_plan = next_plan_after_review(plan, review)
    assert next_plan is not plan
    assert next_plan.version == plan.version + 1
    assert next_plan.focus == "new priority after conflict"
    assert next_plan.selected_style == plan.selected_style
    assert next_plan.id != plan.id


def test_render_includes_lettered_chapter_titles() -> None:
    environment = LocalModelEnvironment(
        base_url="http://127.0.0.1:8080/v1",
        model="test-model",
        api_key="not-needed",
        structured_mode=StructuredOutputMode.JSON_SCHEMA,
    )
    sections = [
        behavioral_report.ReportSection(
            title="A. Safety × style — Acute suicidal ideation (`cbt`)",
            review_focus="boundary",
            excerpts=[("Model reply", "sample")],
        ),
        behavioral_report.ReportSection(
            title="B. Matched-input style differentiation — dream",
            review_focus="style",
            excerpts=[("Reply — `cbt`", "sample")],
        ),
        behavioral_report.ReportSection(
            title="C. Assessment — structured anxiety",
            review_focus="plans",
            excerpts=[("Assessment table", "| Style |")],
        ),
        behavioral_report.ReportSection(
            title="D. Language policy — German profile",
            review_focus="language",
            excerpts=[("Intake reply", "Hallo")],
        ),
        behavioral_report.ReportSection(
            title="E. Longitudinal supervisor — genuine progress",
            review_focus="progress",
            observations=["Session 1 plan_patch_is_noop: False"],
            excerpts=[("Session 2 summary", "progress")],
        ),
        behavioral_report.ReportSection(
            title="F. Historical / current-session attribution",
            review_focus="attribution",
            excerpts=[("Current session summary", "fact B only")],
        ),
        behavioral_report.ReportSection(
            title="Appendix. Intervention selection completeness",
            review_focus="citations",
            excerpts=[("Session summary", "ok")],
        ),
    ]
    text = behavioral_report._render(
        sections,
        environment=environment,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert "A. Safety × style" in text
    assert "B. Matched-input style differentiation" in text
    assert "C. Assessment" in text
    assert "D. Language policy" in text
    assert "E. Longitudinal supervisor" in text
    assert "F. Historical / current-session attribution" in text
    assert "Appendix. Intervention selection completeness" in text
    assert "about 57 provider requests" in text
    assert "test-model" in text
