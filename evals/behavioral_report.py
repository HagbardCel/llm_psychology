"""Diagnostic behavioral report for a configured local model.

Run with `make eval-report` (or `python -m evals.behavioral_report`). The
report answers "what does this model actually say in hard situations", and is
written to `logs/evals/` for human review.

This module makes no semantic quality judgement. Concerning model output is a
finding for the reviewer, not a failure: the exit code reflects only whether
the report could be produced. Anything the product must guarantee belongs in
`test_hard_invariants.py` instead.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from evals.harness import (
    EvalRunner,
    citation_integrity_failures,
    request_extra_body,
    request_timeout_seconds,
)
from evals.scenarios import (
    BEHAVIORAL_SCENARIOS,
    INTERVENTION_COMPLETENESS,
    STYLE_DIFFERENTIATION,
)
from jung.diagnostics import sanitize_url
from jung.llm.errors import LLMError
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


async def _therapy_sections(runner: EvalRunner) -> list[ReportSection]:
    styles = load_styles()
    sections: list[ReportSection] = []

    for scenario in BEHAVIORAL_SCENARIOS:
        reply = await runner.therapy_reply(
            style=styles[scenario.style_id],
            patient_message=scenario.patient_message,
        )
        sections.append(
            ReportSection(
                title=scenario.title,
                review_focus=scenario.review_focus,
                observations=[f"Style: `{scenario.style_id}`"],
                excerpts=[
                    ("Patient message", scenario.patient_message),
                    ("Model reply", reply),
                ],
            )
        )

    return sections


async def _style_section(runner: EvalRunner) -> ReportSection:
    styles = load_styles()
    excerpts: list[tuple[str, str]] = [
        ("Patient message", STYLE_DIFFERENTIATION.patient_message)
    ]
    for style_id in STYLE_DIFFERENTIATION.style_ids:
        reply = await runner.therapy_reply(
            style=styles[style_id],
            patient_message=STYLE_DIFFERENTIATION.patient_message,
        )
        excerpts.append((f"Reply — `{style_id}`", reply))
    return ReportSection(
        title=STYLE_DIFFERENTIATION.title,
        review_focus=STYLE_DIFFERENTIATION.review_focus,
        excerpts=excerpts,
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
        for item in result.session_briefing.intervention_evidence
    ]
    grounded = [
        turn.source_sequence
        for turn in result.derived_profile_patch.grounded_patient_turns
    ]
    integrity = citation_integrity_failures(result, transcript)

    observations = [
        f"Therapist turns delivered: {delivered}",
        f"Therapist turns cited as interventions: {cited or 'none'}",
        f"Patient turns retained as durable context: {grounded or 'none'}",
        f"Citation integrity findings: {integrity or 'none'}",
    ]
    return ReportSection(
        title=scenario.title,
        review_focus=scenario.review_focus,
        observations=observations,
        excerpts=[
            ("Session summary", result.session_summary),
            ("Narrative handoff", result.session_briefing.narrative_handoff),
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
        sections = await _therapy_sections(runner)
        sections.append(await _style_section(runner))
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
