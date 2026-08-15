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

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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
from jung.phases.post_session.merge import plan_patch_is_noop
from jung.styles import load_styles
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


@dataclass(frozen=True, slots=True)
class ReportSection:
    title: str
    review_focus: str
    observations: list[str] = field(default_factory=list)
    excerpts: list[tuple[str, str]] = field(default_factory=list)


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


async def _safety_sections(runner: EvalRunner) -> list[ReportSection]:
    styles = load_styles()
    sections: list[ReportSection] = []
    for scenario in BEHAVIORAL_SCENARIOS:
        for style_id in SAFETY_STYLE_IDS:
            reply = await runner.therapy_reply(
                style=styles[style_id],
                patient_message=scenario.patient_message,
            )
            sections.append(
                ReportSection(
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
            )
    return sections


async def _style_sections(runner: EvalRunner) -> list[ReportSection]:
    styles = load_styles()
    sections: list[ReportSection] = []
    for comparison in STYLE_COMPARISONS:
        excerpts: list[tuple[str, str]] = [
            ("Patient message", comparison.patient_message)
        ]
        for style_id in comparison.style_ids:
            reply = await runner.therapy_reply(
                style=styles[style_id],
                patient_message=comparison.patient_message,
            )
            excerpts.append((f"Reply — `{style_id}`", reply))
        sections.append(
            ReportSection(
                title=f"B. {comparison.title}",
                review_focus=comparison.review_focus,
                excerpts=excerpts,
            )
        )
    return sections


async def _assessment_sections(runner: EvalRunner) -> list[ReportSection]:
    sections: list[ReportSection] = []
    for scenario in ASSESSMENT_SCENARIOS:
        result = await runner.assess(transcript=scenario.transcript())
        lines = [
            "| Style | Score | Rationale | Initial focus | Goals | Interventions |",
            "| --- | ---: | --- | --- | --- | --- |",
        ]
        for item in result.style_recommendations:
            goals = "; ".join(item.initial_plan.goals) or "(none)"
            interventions = (
                "; ".join(item.initial_plan.planned_interventions) or "(none)"
            )
            lines.append(
                f"| `{item.style_id}` | {item.score:.2f} | "
                f"{item.rationale} | {item.initial_plan.focus} | "
                f"{goals} | {interventions} |"
            )
        sections.append(
            ReportSection(
                title=f"C. {scenario.title}",
                review_focus=scenario.review_focus,
                observations=[
                    f"Formulation: {result.formulation}",
                    f"Presenting concerns: {', '.join(result.presenting_concerns)}",
                ],
                excerpts=[("Assessment table", "\n".join(lines))],
            )
        )
    return sections


async def _language_sections(runner: EvalRunner) -> list[ReportSection]:
    styles = load_styles()
    sections: list[ReportSection] = []
    for scenario in LANGUAGE_SCENARIOS:
        profile = eval_profile(primary_language=scenario.profile_language)
        intake_reply = await runner.intake_reply(
            profile=profile,
            patient_message=scenario.patient_message,
        )
        therapy_reply = await runner.therapy_reply(
            style=styles["cbt"],
            patient_message=scenario.patient_message,
            profile=profile,
        )
        sections.append(
            ReportSection(
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
        )
    return sections


async def _longitudinal_sections(runner: EvalRunner) -> list[ReportSection]:
    styles = load_styles()
    sections: list[ReportSection] = []
    for scenario in LONGITUDINAL_SUPERVISOR_SCENARIOS:
        style = styles[scenario.style_id]
        plan_1 = _plan_with_focus(
            scenario.style_id,
            focus=scenario.initial_focus,
            interventions=scenario.initial_interventions,
        )
        result_1 = await runner.post_session(
            style=style,
            transcript=scenario.session_1_transcript(),
            current_plan=plan_1,
        )
        noop = plan_patch_is_noop(plan_1, result_1.review.plan_recommendation)
        plan_2 = next_plan_after_review(plan_1, result_1.review)
        result_2 = await runner.post_session(
            style=style,
            transcript=scenario.session_2_transcript(),
            current_plan=plan_2,
            prior_reviews=(result_1.review,),
        )
        sections.append(
            ReportSection(
                title=f"E. {scenario.title}",
                review_focus=scenario.review_focus,
                observations=[
                    f"Style: `{scenario.style_id}`",
                    f"Session 1 plan version: {plan_1.version}",
                    f"Session 1 plan_patch_is_noop: {noop}",
                    f"Session 2 plan version: {plan_2.version}",
                    f"Session 2 plan focus: {plan_2.focus}",
                    "Session 2 plan identity reused: "
                    f"{plan_2.id == plan_1.id and plan_2.version == plan_1.version}",
                ],
                excerpts=[
                    ("Session 1 summary", result_1.review.analysis.summary),
                    (
                        "Session 1 progress indicators",
                        "\n".join(result_1.review.analysis.progress_indicators)
                        or "(none)",
                    ),
                    (
                        "Session 1 plan patch focus",
                        result_1.review.plan_recommendation.focus or "(unchanged)",
                    ),
                    ("Session 2 summary", result_2.review.analysis.summary),
                    (
                        "Session 2 progress indicators",
                        "\n".join(result_2.review.analysis.progress_indicators)
                        or "(none)",
                    ),
                    (
                        "Session 2 plan patch focus",
                        result_2.review.plan_recommendation.focus or "(unchanged)",
                    ),
                    (
                        "Session 2 narrative handoff",
                        result_2.review.briefing.narrative_handoff,
                    ),
                ],
            )
        )
    return sections


async def _attribution_section(runner: EvalRunner) -> ReportSection:
    scenario = ATTRIBUTION_SCENARIO
    styles = load_styles()
    style = styles[scenario.style_id]
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


async def _intervention_section(runner: EvalRunner) -> ReportSection:
    scenario = INTERVENTION_COMPLETENESS
    styles = load_styles()
    transcript = scenario.transcript()
    result = await runner.post_session(
        style=styles[scenario.style_id],
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


def _render(
    sections: list[ReportSection],
    *,
    environment: LocalModelEnvironment,
    generated_at: datetime,
) -> str:
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


def _write_report(text: str, generated_at: datetime) -> list[Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    paths = [REPORT_DIR / LATEST_REPORT, REPORT_DIR / f"report-{stamp}.md"]
    for path in paths:
        path.write_text(text, encoding="utf-8")
    return paths


async def _collect(environment: LocalModelEnvironment) -> list[ReportSection]:
    client = build_local_model_client(
        environment,
        extra_body=request_extra_body(),
    )
    try:
        runner = EvalRunner(
            gateway=client.gateway,
            policies=build_local_model_policies(
                environment,
                request_timeout_seconds=request_timeout_seconds(),
            ),
        )
        sections: list[ReportSection] = []
        sections.extend(await _safety_sections(runner))
        sections.extend(await _style_sections(runner))
        sections.extend(await _assessment_sections(runner))
        sections.extend(await _language_sections(runner))
        sections.extend(await _longitudinal_sections(runner))
        sections.append(await _attribution_section(runner))
        sections.append(await _intervention_section(runner))
        return sections
    finally:
        await client.aclose()


def main() -> int:
    try:
        environment = resolve_local_model_environment()
    except MissingLocalModelEnv as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_MISSING_ENV

    try:
        sections = asyncio.run(_collect(environment))
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
            _render(sections, environment=environment, generated_at=generated_at),
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
