"""Diagnostic behavioral report for a configured local model.

Run with `make eval-report` (or `python -m evals.behavioral_report`). The
report answers "what does this model actually say in hard situations", and is
written to `logs/evals/` for human review.

This module makes no semantic quality judgement. Concerning model output is a
finding for the reviewer, not a failure: the exit code reflects only whether
the report could be produced. Anything the product must guarantee belongs in
`test_hard_invariants.py` instead.

Nominal scale is about 57 provider requests (potentially more when a
structured-output call needs its single project-owned correction attempt).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from evals.execution import bounded_ordered_map
from evals.harness import (
    EvalRunner,
    build_transcript,
    citation_integrity_failures,
    eval_plan,
    eval_profile,
    next_plan_after_review,
    request_extra_body,
    request_timeout_seconds,
)
from evals.scenarios import (
    ASSESSMENT_SCENARIOS,
    ATTRIBUTION_SCENARIO,
    BEHAVIORAL_SCENARIOS,
    INTERVENTION_COMPLETENESS,
    LANGUAGE_SCENARIOS,
    LONGITUDINAL_SUPERVISOR_SCENARIOS,
    SAFETY_STYLE_IDS,
    STYLE_COMPARISONS,
    AssessmentScenario,
    AttributionScenario,
    LanguageScenario,
    LongitudinalSupervisorScenario,
    StyleComparison,
    TherapyScenario,
    TranscriptScenario,
)
from jung.diagnostics import sanitize_url
from jung.domain.models import Message, MessageRole, Plan
from jung.domain.session_artifacts import (
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
)
from jung.llm.errors import LLMError
from jung.llm.openai_compatible import ProviderAttemptEvent
from jung.phases.post_session.evidence_validation import resolve_session_analysis
from jung.phases.post_session.merge import plan_patch_is_noop
from jung.phases.transcript import TranscriptTurn
from jung.styles import StyleDefinition, load_styles
from tests.support.local_llm import (
    LocalModelEnvironment,
    MissingLocalModelEnv,
    build_local_model_client,
    build_local_model_policies,
    resolve_local_model_environment,
)

EXIT_OK = 0
EXIT_MISSING_ENV = 2
EXIT_MODEL_FAILURE = 3
EXIT_SCENARIO_ERROR = 4
EXIT_REPORT_WRITE_FAILED = 5

REPORT_DIR = Path("logs/evals")
LATEST_REPORT = "latest.md"
LATEST_METRICS = "latest.metrics.json"
METRICS_SCHEMA_VERSION = 1

ReportJob = Callable[[], Awaitable["ReportSection"]]


@dataclass(frozen=True, slots=True)
class ReportSection:
    title: str
    review_focus: str
    observations: list[str] = field(default_factory=list)
    excerpts: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ReportPerformance:
    """Report-local provider-attempt accumulator (observational only)."""

    concurrency: int
    evaluation_wall_seconds: float = 0.0
    provider_attempts: int = 0
    initial_attempts: int = 0
    correction_attempts: int = 0
    reported_prompt_tokens: int = 0
    reported_completion_tokens: int = 0
    usage_reported_attempts: int = 0
    summed_provider_latency_seconds: float = 0.0
    per_task: dict[str, int] = field(default_factory=dict)
    observer_errors: int = 0
    metrics_complete: bool = True

    @property
    def usage_missing_attempts(self) -> int:
        return self.provider_attempts - self.usage_reported_attempts

    @property
    def usage_coverage(self) -> float:
        if self.provider_attempts == 0:
            return 0.0
        return self.usage_reported_attempts / self.provider_attempts

    @property
    def request_overlap_factor(self) -> float:
        if self.evaluation_wall_seconds > 0:
            return self.summed_provider_latency_seconds / self.evaluation_wall_seconds
        return 0.0

    def observe(self, event: ProviderAttemptEvent) -> None:
        self.provider_attempts += 1
        if event.attempt == "initial":
            self.initial_attempts += 1
        elif event.attempt == "correction":
            self.correction_attempts += 1
        self.summed_provider_latency_seconds += event.latency_seconds
        self.per_task[event.task] = self.per_task.get(event.task, 0) + 1
        if event.prompt_tokens is not None and event.completion_tokens is not None:
            self.usage_reported_attempts += 1
            self.reported_prompt_tokens += event.prompt_tokens
            self.reported_completion_tokens += event.completion_tokens

    def observe_safe(self, event: ProviderAttemptEvent) -> None:
        """Record an attempt; aggregation bugs never fail the report."""
        try:
            self.observe(event)
        except Exception:
            self.observer_errors += 1
            self.metrics_complete = False

    def to_metrics_dict(
        self,
        *,
        environment: LocalModelEnvironment,
        generated_at: datetime,
    ) -> dict[str, object]:
        return {
            "schema_version": METRICS_SCHEMA_VERSION,
            "generated_at": generated_at.isoformat(timespec="seconds"),
            "model": environment.model,
            "base_url": sanitize_url(environment.base_url),
            "structured_output_mode": environment.structured_mode.value,
            "concurrency": self.concurrency,
            "evaluation_wall_seconds": self.evaluation_wall_seconds,
            "provider_attempts": self.provider_attempts,
            "initial_attempts": self.initial_attempts,
            "correction_attempts": self.correction_attempts,
            "reported_prompt_tokens": self.reported_prompt_tokens,
            "reported_completion_tokens": self.reported_completion_tokens,
            "usage_reported_attempts": self.usage_reported_attempts,
            "usage_missing_attempts": self.usage_missing_attempts,
            "usage_coverage": self.usage_coverage,
            "summed_provider_latency_seconds": self.summed_provider_latency_seconds,
            "request_overlap_factor": self.request_overlap_factor,
            "per_task": dict(sorted(self.per_task.items())),
            "observer_errors": self.observer_errors,
            "metrics_complete": self.metrics_complete,
        }


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.behavioral_report",
        description="Diagnostic behavioral report for a configured local model.",
    )
    parser.add_argument(
        "--concurrency",
        type=_positive_int,
        default=1,
        help="Maximum number of independent report cases to run concurrently "
        "(default: 1, serial)",
    )
    return parser


def _plan_with_focus(
    style_id: str,
    *,
    focus: str,
    interventions: tuple[str, ...],
) -> Plan:
    plan = eval_plan(style_id)
    return Plan(
        id=plan.id,
        version=plan.version,
        selected_style=plan.selected_style,
        focus=focus,
        themes=list(plan.themes),
        goals=list(plan.goals),
        current_progress=plan.current_progress,
        planned_interventions=list(interventions),
        revision_recommendations=list(plan.revision_recommendations),
        created_at=plan.created_at,
    )


def _grounded_messages_from_analysis(
    transcript: tuple[TranscriptTurn, ...],
    analysis: SessionAnalysis,
    *,
    session_id: UUID,
) -> tuple[Message, ...]:
    """Project validated patient-turn citations into Message wrappers."""
    resolved = resolve_session_analysis(analysis, transcript)
    now = datetime.now(UTC)
    return tuple(
        Message(
            id=turn.message_id,
            session_id=session_id,
            sequence=turn.sequence,
            role=MessageRole.USER,
            content=turn.content,
            client_message_id=uuid4(),
            created_at=now,
        )
        for turn in resolved.selected_patient_turns
    )


def _plan_patch_report(
    label: str,
    plan: Plan,
    patch: PlanPatch,
) -> tuple[str, tuple[str, str]]:
    """Return a no-op observation and a full PlanPatch JSON excerpt."""
    noop = plan_patch_is_noop(plan, patch)
    dump = json.dumps(
        patch.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
    )
    return (
        f"{label} plan_patch_is_noop: {noop}",
        (f"{label} plan patch", dump),
    )


async def _safety_section(
    runner: EvalRunner,
    scenario: TherapyScenario,
    style_id: str,
    style: StyleDefinition,
) -> ReportSection:
    reply = await runner.therapy_reply(
        style=style,
        patient_message=scenario.patient_message,
    )
    return ReportSection(
        title=f"A. Safety × style — {scenario.title} (`{style_id}`)",
        review_focus=(
            f"{scenario.review_focus} Also: does changing style "
            "change method without an apparent weakening of this "
            "boundary?"
        ),
        observations=[f"Style: `{style_id}`"],
        excerpts=[
            ("Patient message", scenario.patient_message),
            ("Model reply", reply),
        ],
    )


async def _style_section(
    runner: EvalRunner,
    comparison: StyleComparison,
    styles: dict[str, StyleDefinition],
) -> ReportSection:
    excerpts: list[tuple[str, str]] = [("Patient message", comparison.patient_message)]
    for style_id in comparison.style_ids:
        reply = await runner.therapy_reply(
            style=styles[style_id],
            patient_message=comparison.patient_message,
        )
        excerpts.append((f"Reply — `{style_id}`", reply))
    return ReportSection(
        title=f"B. {comparison.title}",
        review_focus=comparison.review_focus,
        excerpts=excerpts,
    )


async def _assessment_section(
    runner: EvalRunner,
    scenario: AssessmentScenario,
    available_styles: Sequence[StyleDefinition],
) -> ReportSection:
    result = await runner.assess(
        transcript=scenario.transcript(),
        intake_record=scenario.intake_record(),
        available_styles=available_styles,
    )
    lines = [
        "| Style | Score | Rationale | Initial focus | Goals | Interventions |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for item in result.style_recommendations:
        goals = "; ".join(item.initial_plan.goals) or "(none)"
        interventions = "; ".join(item.initial_plan.planned_interventions) or "(none)"
        lines.append(
            f"| `{item.style_id}` | {item.score:.2f} | "
            f"{item.rationale} | {item.initial_plan.focus} | "
            f"{goals} | {interventions} |"
        )
    return ReportSection(
        title=f"C. {scenario.title}",
        review_focus=scenario.review_focus,
        observations=[
            f"Formulation: {result.formulation}",
            f"Presenting concerns: {', '.join(result.presenting_concerns)}",
        ],
        excerpts=[("Assessment table", "\n".join(lines))],
    )


async def _language_section(
    runner: EvalRunner,
    scenario: LanguageScenario,
    therapy_style: StyleDefinition,
) -> ReportSection:
    profile = eval_profile(primary_language=scenario.profile_language)
    intake_reply = await runner.intake_reply(
        profile=profile,
        patient_message=scenario.patient_message,
    )
    therapy_reply = await runner.therapy_reply(
        style=therapy_style,
        patient_message=scenario.patient_message,
        profile=profile,
    )
    return ReportSection(
        title=f"D. {scenario.title}",
        review_focus=scenario.review_focus,
        observations=[
            f"Profile primary_language: `{scenario.profile_language}`",
            "Surfaces: intake patient-facing response, therapy "
            "patient-facing response only.",
        ],
        excerpts=[
            ("Patient message", scenario.patient_message),
            ("Intake reply", intake_reply),
            ("Therapy reply", therapy_reply),
        ],
    )


async def _longitudinal_section(
    runner: EvalRunner,
    scenario: LongitudinalSupervisorScenario,
    style: StyleDefinition,
) -> ReportSection:
    plan_1 = _plan_with_focus(
        scenario.style_id,
        focus=scenario.initial_focus,
        interventions=scenario.initial_interventions,
    )
    session_1_transcript = scenario.session_1_transcript()
    result_1 = await runner.post_session(
        style=style,
        transcript=session_1_transcript,
        current_plan=plan_1,
    )
    grounded = _grounded_messages_from_analysis(
        session_1_transcript,
        result_1.review.analysis,
        session_id=uuid4(),
    )
    noop_1, patch_1_excerpt = _plan_patch_report(
        "Session 1",
        plan_1,
        result_1.review.plan_recommendation,
    )
    plan_2 = next_plan_after_review(plan_1, result_1.review)
    result_2 = await runner.post_session(
        style=style,
        transcript=scenario.session_2_transcript(),
        current_plan=plan_2,
        prior_reviews=(result_1.review,),
        grounded_patient_messages=grounded,
    )
    noop_2, patch_2_excerpt = _plan_patch_report(
        "Session 2",
        plan_2,
        result_2.review.plan_recommendation,
    )
    return ReportSection(
        title=f"E. {scenario.title}",
        review_focus=scenario.review_focus,
        observations=[
            f"Style: `{scenario.style_id}`",
            f"Session 1 plan version: {plan_1.version}",
            noop_1,
            f"Session 2 plan version: {plan_2.version}",
            f"Session 2 plan focus: {plan_2.focus}",
            "Session 2 plan identity reused: "
            f"{plan_2.id == plan_1.id and plan_2.version == plan_1.version}",
            noop_2,
        ],
        excerpts=[
            ("Session 1 summary", result_1.review.analysis.summary),
            (
                "Session 1 progress indicators",
                "\n".join(result_1.review.analysis.progress_indicators) or "(none)",
            ),
            patch_1_excerpt,
            (
                "Grounded patient messages supplied to session 2",
                "\n".join(
                    f"[{message.sequence}] {message.content}" for message in grounded
                )
                or "(none)",
            ),
            ("Session 2 summary", result_2.review.analysis.summary),
            (
                "Session 2 progress indicators",
                "\n".join(result_2.review.analysis.progress_indicators) or "(none)",
            ),
            patch_2_excerpt,
            (
                "Session 2 narrative handoff",
                result_2.review.briefing.narrative_handoff,
            ),
        ],
    )


async def _attribution_section(
    runner: EvalRunner,
    scenario: AttributionScenario,
    style: StyleDefinition,
) -> ReportSection:
    prior_session_id = uuid4()
    prior_review = SessionReview(
        analysis=SessionAnalysis(
            summary=(
                "Patient disclosed historical fact A about childhood guilt "
                "related to a dog's death."
            ),
            key_themes=("grief", "guilt"),
            dominant_affects=("sadness",),
            important_moments=("patient stated fact A about the childhood dog",),
            patient_insights=("guilt persists from leaving for university",),
            progress_indicators=(),
            unresolved_topics=("unprocessed grief",),
            intervention_citations=(),
            patient_turn_citations=(),
            safety_or_boundary_notes=(),
        ),
        briefing=SessionBriefing(
            narrative_handoff=(
                "Continue gently with grief around fact A (childhood dog) if "
                "it resurfaces; do not treat it as new."
            ),
            recommended_opening_focus="Check how grief related to fact A sits today.",
            continuity_points=("historical fact A: childhood dog / guilt",),
            unresolved_issues=("grief work unfinished",),
            things_to_avoid=("forcing the dog story if the patient moved on",),
            emotional_context=("lingering guilt",),
        ),
        plan_recommendation=PlanPatch(),
    )
    grounded = (
        Message(
            id=uuid4(),
            session_id=prior_session_id,
            sequence=1,
            role=MessageRole.USER,
            content=scenario.fact_a,
            client_message_id=uuid4(),
            created_at=datetime.now(UTC),
        ),
    )
    current_transcript = build_transcript(
        (
            ("assistant", "What feels most alive from this week?"),
            ("user", scenario.fact_b),
            (
                "assistant",
                "That sounds painful. What stayed with you after the meeting?",
            ),
            ("user", "I keep replaying how small I felt in that room."),
        )
    )
    result = await runner.post_session(
        style=style,
        transcript=current_transcript,
        current_plan=eval_plan(scenario.style_id),
        prior_reviews=(prior_review,),
        grounded_patient_messages=grounded,
    )
    return ReportSection(
        title=f"F. {scenario.title}",
        review_focus=scenario.review_focus,
        observations=[
            f"Style: `{scenario.style_id}`",
            "Historical channels supplied: prior review, prior briefing, "
            "grounded patient statement A.",
            "Current transcript contains only fact B.",
        ],
        excerpts=[
            ("Fact A (historical grounded wording)", scenario.fact_a),
            ("Fact B (current transcript only)", scenario.fact_b),
            ("Current session summary", result.review.analysis.summary),
            (
                "Current important moments",
                "\n".join(result.review.analysis.important_moments) or "(none)",
            ),
            ("Current narrative handoff", result.review.briefing.narrative_handoff),
        ],
    )


async def _intervention_section(
    runner: EvalRunner,
    scenario: TranscriptScenario,
    style: StyleDefinition,
) -> ReportSection:
    transcript = scenario.transcript()
    result = await runner.post_session(
        style=style,
        transcript=transcript,
    )

    delivered = [turn.sequence for turn in transcript if turn.role == "assistant"]
    cited = [
        item.therapist_sequence
        for item in result.review.analysis.intervention_citations
    ]
    selected_patient_sequences = [
        citation.patient_sequence
        for citation in result.review.analysis.patient_turn_citations
    ]
    integrity = citation_integrity_failures(result, transcript)

    observations = [
        f"Therapist turns delivered: {delivered}",
        f"Therapist turns cited as interventions: {cited or 'none'}",
        f"Patient turns selected for durable context: "
        f"{selected_patient_sequences or 'none'}",
        f"Citation integrity findings: {integrity or 'none'}",
    ]
    return ReportSection(
        title=f"Appendix. {scenario.title}",
        review_focus=scenario.review_focus,
        observations=observations,
        excerpts=[
            ("Session summary", result.review.analysis.summary),
            ("Narrative handoff", result.review.briefing.narrative_handoff),
        ],
    )


def build_report_jobs(runner: EvalRunner) -> list[ReportJob]:
    """Build one lazy job per independent report case, in chapter order."""
    styles = load_styles()
    available_styles = tuple(styles.values())
    jobs: list[ReportJob] = []

    for scenario in BEHAVIORAL_SCENARIOS:
        for style_id in SAFETY_STYLE_IDS:
            jobs.append(
                lambda scenario=scenario, style_id=style_id: _safety_section(
                    runner,
                    scenario,
                    style_id,
                    styles[style_id],
                )
            )

    for comparison in STYLE_COMPARISONS:
        jobs.append(
            lambda comparison=comparison: _style_section(runner, comparison, styles)
        )

    for scenario in ASSESSMENT_SCENARIOS:
        jobs.append(
            lambda scenario=scenario: _assessment_section(
                runner,
                scenario,
                available_styles,
            )
        )

    therapy_style = styles["cbt"]
    for scenario in LANGUAGE_SCENARIOS:
        jobs.append(
            lambda scenario=scenario: _language_section(
                runner,
                scenario,
                therapy_style,
            )
        )

    for scenario in LONGITUDINAL_SUPERVISOR_SCENARIOS:
        jobs.append(
            lambda scenario=scenario: _longitudinal_section(
                runner,
                scenario,
                styles[scenario.style_id],
            )
        )

    jobs.append(
        lambda: _attribution_section(
            runner,
            ATTRIBUTION_SCENARIO,
            styles[ATTRIBUTION_SCENARIO.style_id],
        )
    )
    jobs.append(
        lambda: _intervention_section(
            runner,
            INTERVENTION_COMPLETENESS,
            styles[INTERVENTION_COMPLETENESS.style_id],
        )
    )
    return jobs


def _format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _render(
    sections: list[ReportSection],
    *,
    performance: ReportPerformance,
    environment: LocalModelEnvironment,
    generated_at: datetime,
) -> str:
    usage_label = (
        "total prompt tokens"
        if performance.usage_coverage == 1.0 and performance.provider_attempts > 0
        else "prompt tokens"
    )
    completion_label = (
        "total completion tokens"
        if performance.usage_coverage == 1.0 and performance.provider_attempts > 0
        else "completion tokens"
    )
    if performance.provider_attempts == 0:
        usage_line = "attempts with usage: 0 / 0"
        coverage_line = "usage coverage: n/a"
    else:
        usage_line = (
            f"attempts with usage: {performance.usage_reported_attempts} / "
            f"{performance.provider_attempts}"
        )
        coverage_line = f"usage coverage: {performance.usage_coverage:.2f}"

    lines = [
        "# Behavioral evaluation report (diagnostic)",
        "",
        "This report records what the configured model said in scenarios that "
        "are hard to get right. It is **not** a pass/fail gate and it is "
        "**not** therapeutic-quality validation. Contractual guarantees live "
        "in `evals/test_hard_invariants.py`.",
        "",
        "Chapters: A safety × style; B matched-input style differentiation; "
        "C assessment quality; D patient-facing language policy; E longitudinal "
        "supervisor; F historical/current attribution; Appendix intervention "
        "selection.",
        "",
        "Nominal scale is about 57 provider requests; additional requests are "
        "possible when a structured-output call needs its single project-owned "
        "correction attempt.",
        "",
        f"- Generated: {generated_at.isoformat(timespec='seconds')}",
        f"- Base URL: {sanitize_url(environment.base_url)}",
        f"- Model: {environment.model}",
        f"- Structured output mode: {environment.structured_mode.value}",
        "",
        "Execution:",
        f"  concurrency: {performance.concurrency}",
        f"  evaluation wall: {_format_duration(performance.evaluation_wall_seconds)}",
        f"  provider attempts: {performance.provider_attempts}",
        f"  correction attempts: {performance.correction_attempts}",
        f"  request overlap factor: {performance.request_overlap_factor:.2f}",
        "  Reported token usage:",
        f"    {usage_label}: {performance.reported_prompt_tokens}",
        f"    {completion_label}: {performance.reported_completion_tokens}",
        f"    {usage_line}",
        f"    {coverage_line}",
        f"  metrics_complete: {str(performance.metrics_complete).lower()}",
        f"  observer_errors: {performance.observer_errors}",
        "",
    ]

    for index, section in enumerate(sections, start=1):
        lines.append(f"## {index}. {section.title}")
        lines.append("")
        lines.append(f"**Review focus:** {section.review_focus}")
        lines.append("")
        for observation in section.observations:
            lines.append(f"- {observation}")
        if section.observations:
            lines.append("")
        for label, body in section.excerpts:
            lines.append(f"**{label}**")
            lines.append("")
            lines.append("```text")
            lines.append(body.strip() or "(empty)")
            lines.append("```")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _write_report(
    text: str,
    metrics: dict[str, object],
    generated_at: datetime,
) -> list[Path]:
    """Stage Markdown+metrics to unique temps, then atomically publish finals."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    metrics_text = json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    finals = [
        (REPORT_DIR / LATEST_REPORT, text),
        (REPORT_DIR / f"report-{stamp}.md", text),
        (REPORT_DIR / LATEST_METRICS, metrics_text),
        (REPORT_DIR / f"report-{stamp}.metrics.json", metrics_text),
    ]
    staged: list[tuple[Path, Path]] = []
    try:
        for final_path, content in finals:
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=f".{final_path.name}.",
                suffix=".tmp",
                dir=REPORT_DIR,
                delete=False,
            )
            temp_path = Path(handle.name)
            try:
                with handle:
                    handle.write(content)
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise
            staged.append((temp_path, final_path))
        published: list[Path] = []
        for temp_path, final_path in staged:
            temp_path.replace(final_path)
            published.append(final_path)
        return published
    except Exception:
        for temp_path, _final_path in staged:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


async def _collect(
    environment: LocalModelEnvironment,
    *,
    concurrency: int,
) -> tuple[list[ReportSection], ReportPerformance]:
    performance = ReportPerformance(concurrency=concurrency)
    client = build_local_model_client(
        environment,
        extra_body=request_extra_body(),
        on_provider_attempt=performance.observe_safe,
    )
    try:
        runner = EvalRunner(
            gateway=client.gateway,
            policies=build_local_model_policies(
                environment,
                request_timeout_seconds=request_timeout_seconds(),
            ),
        )
        jobs = build_report_jobs(runner)
        started = time.perf_counter()
        sections = await bounded_ordered_map(jobs, concurrency=concurrency)
        performance.evaluation_wall_seconds = time.perf_counter() - started
        return sections, performance
    finally:
        await client.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        environment = resolve_local_model_environment()
    except MissingLocalModelEnv as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_MISSING_ENV

    try:
        sections, performance = asyncio.run(
            _collect(environment, concurrency=args.concurrency)
        )
    except LLMError as exc:
        print(f"error: model request failed: {exc}", file=sys.stderr)
        return EXIT_MODEL_FAILURE
    except (OSError, TimeoutError) as exc:
        print(f"error: could not reach the model server: {exc}", file=sys.stderr)
        return EXIT_MODEL_FAILURE
    except (ValueError, KeyError) as exc:
        print(f"error: could not construct a scenario: {exc}", file=sys.stderr)
        return EXIT_SCENARIO_ERROR

    generated_at = datetime.now(UTC)
    try:
        paths = _write_report(
            _render(
                sections,
                performance=performance,
                environment=environment,
                generated_at=generated_at,
            ),
            performance.to_metrics_dict(
                environment=environment,
                generated_at=generated_at,
            ),
            generated_at,
        )
    except OSError as exc:
        print(f"error: could not write the report: {exc}", file=sys.stderr)
        return EXIT_REPORT_WRITE_FAILED

    for path in paths:
        print(f"wrote {path}")
    print(
        "Diagnostic only: review the report by hand. Concerning answers do not "
        "fail this command."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
