"""Deterministic tests for behavioral report scenarios and helpers."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from evals import behavioral_report
from evals.harness import build_transcript, eval_plan, next_plan_after_review
from evals.scenarios import (
    ASSESSMENT_SCENARIOS,
    ATTRIBUTION_SCENARIO,
    BEHAVIORAL_SCENARIOS,
    LANGUAGE_SCENARIOS,
    LONGITUDINAL_SUPERVISOR_SCENARIOS,
    SAFETY_STYLE_IDS,
    STYLE_COMPARISONS,
)
from jung.domain.models import MessageRole
from jung.domain.session_artifacts import (
    PatientTurnCitation,
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


def _analysis_with_patient_citations(
    *sequences: int,
) -> SessionAnalysis:
    return SessionAnalysis(
        summary="Session summary.",
        key_themes=("anxiety",),
        patient_turn_citations=tuple(
            PatientTurnCitation(patient_sequence=sequence) for sequence in sequences
        ),
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


def test_grounded_messages_from_analysis_empty_citations() -> None:
    transcript = build_transcript(
        (
            ("assistant", "What feels important?"),
            ("user", "I feel anxious before meetings."),
        )
    )
    session_id = uuid4()
    messages = behavioral_report._grounded_messages_from_analysis(
        transcript,
        _analysis_with_patient_citations(),
        session_id=session_id,
    )
    assert messages == ()


def test_grounded_messages_from_analysis_preserves_resolver_order() -> None:
    transcript = build_transcript(
        (
            ("assistant", "What feels important?"),
            ("user", "First patient turn about blushing."),
            ("assistant", "Tell me more."),
            ("user", "Second patient turn about leaving early."),
            ("assistant", "What happened next?"),
            ("user", "Third patient turn about rumination."),
        )
    )
    session_id = uuid4()
    # Citation tuple order is reverse; resolver returns ascending sequence.
    messages = behavioral_report._grounded_messages_from_analysis(
        transcript,
        _analysis_with_patient_citations(6, 2, 4),
        session_id=session_id,
    )
    assert [message.sequence for message in messages] == [2, 4, 6]
    by_sequence = {turn.sequence: turn for turn in transcript}
    for message in messages:
        source = by_sequence[message.sequence]
        assert message.id == source.message_id
        assert message.content == source.content
        assert message.role is MessageRole.USER
        assert message.session_id == session_id


def test_plan_patch_report_shows_non_focus_change() -> None:
    plan = eval_plan("cbt")
    patch = PlanPatch(
        focus=None,
        planned_interventions=("new intervention",),
    )
    observation, excerpt = behavioral_report._plan_patch_report(
        "Session 2",
        plan,
        patch,
    )
    assert observation == "Session 2 plan_patch_is_noop: False"
    title, dump = excerpt
    assert title == "Session 2 plan patch"
    assert '"focus": null' in dump
    assert '"planned_interventions": ["new intervention"]' in dump


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
    performance = behavioral_report.ReportPerformance(
        concurrency=1,
        workload="full",
        report_jobs=34,
    )
    text = behavioral_report._render(
        sections,
        performance=performance,
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
    assert "workload: full" in text
    assert "report jobs: 34" in text
    assert "nominal provider requests: about 57" in text
    assert "test-model" in text
    assert "Execution:" in text
    assert "concurrency: 1" in text
    assert "attempts with usage: 0 / 0" in text
    assert "usage coverage: n/a" in text
    assert "metrics_complete: true" in text
    assert "observer_errors: 0" in text
    assert "total prompt tokens" not in text
    assert "request overlap factor: 0.00" in text


def test_render_screen_workload_nominal_scale() -> None:
    environment = LocalModelEnvironment(
        base_url="http://127.0.0.1:8080/v1",
        model="test-model",
        api_key="not-needed",
        structured_mode=StructuredOutputMode.JSON_SCHEMA,
    )
    performance = behavioral_report.ReportPerformance(
        concurrency=4,
        workload="screen",
        report_jobs=8,
    )
    text = behavioral_report._render(
        [
            behavioral_report.ReportSection(
                title="A. sample",
                review_focus="focus",
                excerpts=[("Model reply", "ok")],
            )
        ],
        performance=performance,
        environment=environment,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert "workload: screen" in text
    assert "report jobs: 8" in text
    assert "nominal provider requests: about 15" in text
    assert "about 15 provider requests" in text


def test_parser_accepts_positive_concurrency() -> None:
    parser = behavioral_report.build_parser()
    for value in (1, 2, 4):
        args = parser.parse_args(["--concurrency", str(value)])
        assert args.concurrency == value
    assert parser.parse_args([]).concurrency == 1


def test_parser_rejects_non_positive_concurrency() -> None:
    parser = behavioral_report.build_parser()
    for value in ("0", "-1"):
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--concurrency", value])
        assert exc_info.value.code == 2


def test_parser_accepts_workload_choices() -> None:
    parser = behavioral_report.build_parser()
    assert parser.parse_args([]).workload == "full"
    assert parser.parse_args(["--workload", "full"]).workload == "full"
    assert parser.parse_args(["--workload", "screen"]).workload == "screen"


def test_parser_rejects_unknown_workload() -> None:
    parser = behavioral_report.build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--workload", "scren"])
    assert exc_info.value.code == 2


def test_build_report_jobs_rejects_unknown_workload() -> None:
    from evals.harness import EvalRunner
    from tests.support.fake_llm import FakeLLM

    runner = EvalRunner(gateway=FakeLLM([]), policies={})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="workload must be"):
        behavioral_report.build_report_jobs(runner, workload="scren")  # type: ignore[arg-type]


def test_report_job_ids_full_and_screen() -> None:
    from evals.harness import EvalRunner
    from tests.support.fake_llm import FakeLLM

    runner = EvalRunner(gateway=FakeLLM([]), policies={})  # type: ignore[arg-type]
    full_ids = tuple(
        job.id for job in behavioral_report.build_report_jobs(runner, workload="full")
    )
    screen_ids = tuple(
        job.id for job in behavioral_report.build_report_jobs(runner, workload="screen")
    )
    assert len(full_ids) == 34
    assert len(full_ids) == len(set(full_ids))
    assert screen_ids == behavioral_report.SCREEN_JOB_IDS
    assert set(behavioral_report.SCREEN_JOB_IDS) <= set(full_ids)


def test_nominal_provider_requests_by_workload() -> None:
    assert behavioral_report.NOMINAL_PROVIDER_REQUESTS["full"] == 57
    assert behavioral_report.NOMINAL_PROVIDER_REQUESTS["screen"] == 15


def test_workload_does_not_change_concurrency_semantics() -> None:
    full_perf = behavioral_report.ReportPerformance(
        concurrency=4, workload="full", report_jobs=34
    )
    screen_perf = behavioral_report.ReportPerformance(
        concurrency=4, workload="screen", report_jobs=8
    )
    assert full_perf.concurrency == screen_perf.concurrency == 4
    assert full_perf.report_jobs == 34
    assert screen_perf.report_jobs == 8
    assert len(behavioral_report.SCREEN_JOB_IDS) == 8


def test_screen_job_ids_are_strict_subset_of_full_inventory() -> None:
    from evals.harness import EvalRunner
    from tests.support.fake_llm import FakeLLM

    runner = EvalRunner(gateway=FakeLLM([]), policies={})  # type: ignore[arg-type]
    full_ids = {
        job.id for job in behavioral_report.build_report_jobs(runner, workload="full")
    }
    screen_ids = set(behavioral_report.SCREEN_JOB_IDS)
    assert screen_ids < full_ids
    assert len(full_ids) - len(screen_ids) == 26


@pytest.mark.asyncio
async def test_build_report_jobs_execute_in_chapter_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove A→Appendix order by running the actual lazy jobs (helpers stubbed)."""
    from evals.execution import bounded_ordered_map
    from evals.harness import EvalRunner
    from evals.scenarios import INTERVENTION_COMPLETENESS
    from tests.support.fake_llm import FakeLLM

    async def stub_safety(runner, scenario, style_id, style):  # type: ignore[no-untyped-def]
        return behavioral_report.ReportSection(
            title=f"A. Safety × style — {scenario.title} (`{style_id}`)",
            review_focus="stub",
            observations=[f"key={scenario.key}", f"style={style_id}"],
            excerpts=[("stub", "ok")],
        )

    async def stub_style(runner, comparison, styles):  # type: ignore[no-untyped-def]
        return behavioral_report.ReportSection(
            title=f"B. {comparison.title}",
            review_focus="stub",
            observations=[f"key={comparison.key}"],
            excerpts=[("stub", "ok")],
        )

    async def stub_assessment(runner, scenario, available_styles):  # type: ignore[no-untyped-def]
        return behavioral_report.ReportSection(
            title=f"C. {scenario.title}",
            review_focus="stub",
            observations=[f"key={scenario.key}"],
            excerpts=[("stub", "ok")],
        )

    async def stub_language(runner, scenario, therapy_style):  # type: ignore[no-untyped-def]
        return behavioral_report.ReportSection(
            title=f"D. {scenario.title}",
            review_focus="stub",
            observations=[f"key={scenario.key}"],
            excerpts=[("stub", "ok")],
        )

    async def stub_longitudinal(runner, scenario, style):  # type: ignore[no-untyped-def]
        return behavioral_report.ReportSection(
            title=f"E. {scenario.title}",
            review_focus="stub",
            observations=[f"key={scenario.key}"],
            excerpts=[("stub", "ok")],
        )

    async def stub_attribution(runner, scenario, style):  # type: ignore[no-untyped-def]
        return behavioral_report.ReportSection(
            title=f"F. {scenario.title}",
            review_focus="stub",
            observations=[f"key={scenario.key}"],
            excerpts=[("stub", "ok")],
        )

    async def stub_intervention(runner, scenario, style):  # type: ignore[no-untyped-def]
        return behavioral_report.ReportSection(
            title=f"Appendix. {scenario.title}",
            review_focus="stub",
            observations=[f"key={scenario.key}"],
            excerpts=[("stub", "ok")],
        )

    monkeypatch.setattr(behavioral_report, "_safety_section", stub_safety)
    monkeypatch.setattr(behavioral_report, "_style_section", stub_style)
    monkeypatch.setattr(behavioral_report, "_assessment_section", stub_assessment)
    monkeypatch.setattr(behavioral_report, "_language_section", stub_language)
    monkeypatch.setattr(behavioral_report, "_longitudinal_section", stub_longitudinal)
    monkeypatch.setattr(behavioral_report, "_attribution_section", stub_attribution)
    monkeypatch.setattr(behavioral_report, "_intervention_section", stub_intervention)

    runner = EvalRunner(gateway=FakeLLM([]), policies={})  # type: ignore[arg-type]
    jobs = behavioral_report.build_report_jobs(runner, workload="full")
    assert all(isinstance(job, behavioral_report.ReportJob) for job in jobs)
    sections = await bounded_ordered_map(jobs, concurrency=1)
    assert len(sections) == 34

    for index, section in enumerate(sections[:18]):
        assert section.title.startswith("A.")
        scenario = BEHAVIORAL_SCENARIOS[index // len(SAFETY_STYLE_IDS)]
        style_id = SAFETY_STYLE_IDS[index % len(SAFETY_STYLE_IDS)]
        assert scenario.key in section.observations[0]
        assert style_id in section.observations[1]
        assert f"(`{style_id}`)" in section.title

    for offset, comparison in enumerate(STYLE_COMPARISONS):
        section = sections[18 + offset]
        assert section.title.startswith("B.")
        assert section.title == f"B. {comparison.title}"
        assert f"key={comparison.key}" in section.observations

    for offset, scenario in enumerate(ASSESSMENT_SCENARIOS):
        section = sections[21 + offset]
        assert section.title.startswith("C.")
        assert section.title == f"C. {scenario.title}"
        assert f"key={scenario.key}" in section.observations

    for offset, scenario in enumerate(LANGUAGE_SCENARIOS):
        section = sections[25 + offset]
        assert section.title.startswith("D.")
        assert section.title == f"D. {scenario.title}"
        assert f"key={scenario.key}" in section.observations

    for offset, scenario in enumerate(LONGITUDINAL_SUPERVISOR_SCENARIOS):
        section = sections[28 + offset]
        assert section.title.startswith("E.")
        assert section.title == f"E. {scenario.title}"
        assert f"key={scenario.key}" in section.observations

    assert sections[32].title.startswith("F.")
    assert sections[32].title == f"F. {ATTRIBUTION_SCENARIO.title}"
    assert f"key={ATTRIBUTION_SCENARIO.key}" in sections[32].observations

    assert sections[33].title.startswith("Appendix.")
    assert sections[33].title == f"Appendix. {INTERVENTION_COMPLETENESS.title}"
    assert f"key={INTERVENTION_COMPLETENESS.key}" in sections[33].observations


@pytest.mark.asyncio
async def test_longitudinal_session_2_waits_for_session_1() -> None:
    from jung.domain.session_artifacts import (
        PlanPatch,
        SessionAnalysis,
        SessionBriefing,
        SessionReview,
    )
    from jung.phases.post_session.models import PostSessionResult
    from jung.styles import load_styles

    scenario = LONGITUDINAL_SUPERVISOR_SCENARIOS[0]
    style = load_styles()[scenario.style_id]
    session_1_done = asyncio.Event()
    session_2_started_before_1 = False
    call_count = 0

    class FakeRunner:
        async def post_session(self, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count, session_2_started_before_1
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(0.02)
                session_1_done.set()
            else:
                if not session_1_done.is_set():
                    session_2_started_before_1 = True
            return PostSessionResult(
                review=SessionReview(
                    analysis=SessionAnalysis(
                        summary=f"session-{call_count}",
                        key_themes=("t",),
                    ),
                    briefing=SessionBriefing(
                        narrative_handoff="handoff",
                        recommended_opening_focus="focus",
                    ),
                    plan_recommendation=PlanPatch(),
                )
            )

    section = await behavioral_report._longitudinal_section(
        FakeRunner(),  # type: ignore[arg-type]
        scenario,
        style,
    )
    assert call_count == 2
    assert session_2_started_before_1 is False
    assert section.title.startswith("E.")


@pytest.mark.asyncio
async def test_independent_longitudinal_jobs_may_overlap() -> None:
    from evals.execution import bounded_ordered_map
    from jung.domain.session_artifacts import (
        PlanPatch,
        SessionAnalysis,
        SessionBriefing,
        SessionReview,
    )
    from jung.phases.post_session.models import PostSessionResult
    from jung.styles import load_styles

    styles = load_styles()
    scenarios = LONGITUDINAL_SUPERVISOR_SCENARIOS[:2]
    first_calls_active = 0
    first_peak = 0
    first_lock = asyncio.Lock()
    both_first = asyncio.Event()

    class TrackingRunner:
        async def post_session(self, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal first_calls_active, first_peak
            async with first_lock:
                first_calls_active += 1
                first_peak = max(first_peak, first_calls_active)
                if first_calls_active == 2:
                    both_first.set()
            await both_first.wait()
            async with first_lock:
                first_calls_active -= 1
            return PostSessionResult(
                review=SessionReview(
                    analysis=SessionAnalysis(
                        summary="summary",
                        key_themes=("t",),
                    ),
                    briefing=SessionBriefing(
                        narrative_handoff="handoff",
                        recommended_opening_focus="focus",
                    ),
                    plan_recommendation=PlanPatch(),
                )
            )

    tracker = TrackingRunner()
    sections = await bounded_ordered_map(
        [
            (
                lambda scenario=scenario: behavioral_report._longitudinal_section(
                    tracker,  # type: ignore[arg-type]
                    scenario,
                    styles[scenario.style_id],
                )
            )
            for scenario in scenarios
        ],
        concurrency=2,
    )
    assert len(sections) == 2
    assert first_peak >= 2
    assert all(section.title.startswith("E.") for section in sections)


def _attempt(
    *,
    task: str = "therapy_response",
    attempt: str = "initial",
    latency_seconds: float = 1.0,
    prompt_chars: int = 100,
    response_format_chars: int | None = None,
    prompt_tokens: int | None = 10,
    completion_tokens: int | None = 5,
) -> object:
    from jung.llm.openai_compatible import ProviderAttemptEvent

    return ProviderAttemptEvent(
        task=task,
        attempt=attempt,  # type: ignore[arg-type]
        status="success",
        latency_seconds=latency_seconds,
        prompt_chars=prompt_chars,
        response_format_chars=response_format_chars,
        response_chars=50,
        timeout_seconds=30.0,
        max_completion_tokens=None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def test_report_performance_counts_usage_and_attempts() -> None:
    perf = behavioral_report.ReportPerformance(concurrency=2)
    perf.observe(_attempt())  # type: ignore[arg-type]
    perf.observe(
        _attempt(  # type: ignore[arg-type]
            task="assessment",
            attempt="correction",
            latency_seconds=3.0,
            prompt_chars=250,
            response_format_chars=40,
            prompt_tokens=20,
            completion_tokens=8,
        )
    )
    perf.observe(
        _attempt(  # type: ignore[arg-type]
            prompt_chars=80,
            prompt_tokens=None,
            completion_tokens=7,
        )
    )
    perf.observe(
        _attempt(  # type: ignore[arg-type]
            prompt_chars=180,
            response_format_chars=15,
            prompt_tokens=4,
            completion_tokens=None,
        )
    )
    perf.evaluation_wall_seconds = 2.0

    assert perf.provider_attempts == 4
    assert perf.initial_attempts == 3
    assert perf.correction_attempts == 1
    assert perf.usage_reported_attempts == 2
    assert perf.usage_missing_attempts == 2
    assert perf.reported_prompt_tokens == 30
    assert perf.reported_completion_tokens == 13
    assert perf.usage_coverage == 0.5
    assert perf.request_overlap_factor == 3.0  # (1+3+1+1)/2
    assert perf.prompt_chars_total == 610
    assert perf.response_format_chars_total == 55
    assert perf.max_prompt_chars == 250
    assert perf.per_task == {"therapy_response": 3, "assessment": 1}
    assert perf.metrics_complete is True


def test_report_performance_zero_wall_and_zero_attempts() -> None:
    perf = behavioral_report.ReportPerformance(concurrency=1)
    assert perf.usage_coverage == 0.0
    assert perf.request_overlap_factor == 0.0
    environment = LocalModelEnvironment(
        base_url="http://127.0.0.1:8080/v1",
        model="test-model",
        api_key="not-needed",
        structured_mode=StructuredOutputMode.JSON_SCHEMA,
    )
    payload = perf.to_metrics_dict(
        environment=environment,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert payload["usage_coverage"] == 0.0
    assert payload["request_overlap_factor"] == 0.0
    assert payload["prompt_chars_total"] == 0
    assert payload["response_format_chars_total"] == 0
    assert payload["max_prompt_chars"] == 0
    assert payload["schema_version"] == 1
    assert payload["workload"] == "full"
    assert payload["report_jobs"] == 0


def test_to_metrics_dict_includes_workload_and_report_jobs() -> None:
    environment = LocalModelEnvironment(
        base_url="http://127.0.0.1:8080/v1",
        model="test-model",
        api_key="not-needed",
        structured_mode=StructuredOutputMode.JSON_SCHEMA,
    )
    perf = behavioral_report.ReportPerformance(
        concurrency=4,
        workload="screen",
        report_jobs=8,
    )
    payload = perf.to_metrics_dict(
        environment=environment,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert payload["workload"] == "screen"
    assert payload["report_jobs"] == 8
    assert payload["concurrency"] == 4
    assert payload["schema_version"] == 1


def test_observe_safe_records_observer_errors() -> None:
    perf = behavioral_report.ReportPerformance(concurrency=1)

    def broken_observe(_event: object) -> None:
        raise RuntimeError("aggregation bug")

    perf.observe = broken_observe  # type: ignore[method-assign]
    perf.observe_safe(_attempt())  # type: ignore[arg-type]
    assert perf.observer_errors == 1
    assert perf.metrics_complete is False
    assert perf.provider_attempts == 0


def test_render_uses_total_token_labels_only_at_full_coverage() -> None:
    environment = LocalModelEnvironment(
        base_url="http://127.0.0.1:8080/v1",
        model="test-model",
        api_key="not-needed",
        structured_mode=StructuredOutputMode.JSON_SCHEMA,
    )
    perf = behavioral_report.ReportPerformance(
        concurrency=4,
        workload="full",
        report_jobs=34,
    )
    perf.observe(
        _attempt(  # type: ignore[arg-type]
            prompt_chars=120,
            response_format_chars=30,
            prompt_tokens=11,
            completion_tokens=9,
        )
    )
    perf.evaluation_wall_seconds = 1.0
    text = behavioral_report._render(
        [
            behavioral_report.ReportSection(
                title="A. sample",
                review_focus="focus",
                excerpts=[("Model reply", "ok")],
            )
        ],
        performance=perf,
        environment=environment,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert "total prompt tokens: 11" in text
    assert "total completion tokens: 9" in text
    assert "attempts with usage: 1 / 1" in text
    assert "workload: full" in text
    assert "report jobs: 34" in text
    assert "concurrency: 4" in text
    assert "request overlap factor: 1.00" in text
    assert "prompt chars total: 120" in text
    assert "response format chars total: 30" in text
    assert "max prompt chars: 120" in text


def test_write_report_publishes_all_four_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(behavioral_report, "REPORT_DIR", tmp_path)
    generated_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    paths = behavioral_report._write_report(
        "# report\n",
        {"schema_version": 1, "concurrency": 1},
        generated_at,
    )
    stamp = "20260101T120000Z"
    assert paths == [
        tmp_path / "latest.md",
        tmp_path / f"report-{stamp}.md",
        tmp_path / "latest.metrics.json",
        tmp_path / f"report-{stamp}.metrics.json",
    ]
    for path in paths:
        assert path.is_file()
    assert (tmp_path / "latest.md").read_text(encoding="utf-8") == "# report\n"
    assert '"concurrency": 1' in (tmp_path / "latest.metrics.json").read_text(
        encoding="utf-8"
    )
    assert not list(tmp_path.glob("*.tmp"))


def test_write_report_staging_failure_leaves_prior_finals_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(behavioral_report, "REPORT_DIR", tmp_path)
    prior_md = tmp_path / "latest.md"
    prior_metrics = tmp_path / "latest.metrics.json"
    prior_md.write_text("PRIOR_MARKDOWN\n", encoding="utf-8")
    prior_metrics.write_text('{"prior": true}\n', encoding="utf-8")

    real_ntf = tempfile.NamedTemporaryFile
    calls = {"n": 0}

    def flaky_ntf(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        handle = real_ntf(*args, **kwargs)
        if calls["n"] == 3:
            handle.close()
            Path(handle.name).unlink(missing_ok=True)
            raise OSError("simulated staging failure")
        return handle

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", flaky_ntf)

    with pytest.raises(OSError, match="simulated staging failure"):
        behavioral_report._write_report(
            "# NEW_REPORT\n",
            {"schema_version": 1, "concurrency": 4},
            datetime(2026, 1, 2, tzinfo=UTC),
        )

    assert prior_md.read_text(encoding="utf-8") == "PRIOR_MARKDOWN\n"
    assert prior_metrics.read_text(encoding="utf-8") == '{"prior": true}\n'
    assert not (tmp_path / "report-20260102T000000Z.md").exists()
    assert not (tmp_path / "report-20260102T000000Z.metrics.json").exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert "NEW_REPORT" not in prior_md.read_text(encoding="utf-8")
