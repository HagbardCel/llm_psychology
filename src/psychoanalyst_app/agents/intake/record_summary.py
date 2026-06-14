"""Prompt summaries for structured intake records."""

from __future__ import annotations

from psychoanalyst_app.agents.intake.record_completeness import IntakeCompleteness
from psychoanalyst_app.models.intake_record import IntakeEvidence, IntakeRecord


def _value(evidence: IntakeEvidence) -> str | None:
    if evidence.is_present() or evidence.is_unable_or_unknown():
        return evidence.value
    return None


def summarize_intake_record_for_prompt(
    record: IntakeRecord,
    completeness: IntakeCompleteness | None = None,
) -> str:
    """Return a compact text summary suitable for the intake response prompt."""
    known = [
        ("Main concern", _value(record.presenting_problem.main_concern)),
        (
            "Time course",
            _value(record.presenting_problem.time_course.duration_or_onset)
            or _value(record.presenting_problem.time_course.frequency),
        ),
        ("Sleep", _value(record.presenting_problem.sleep_impact)),
        (
            "Functional impact",
            _value(record.presenting_problem.functional_impairment),
        ),
        (
            "Coping",
            ", ".join(
                item.value or ""
                for item in record.coping.attempted_strategies
                if item.is_addressed()
            )
            or _value(record.coping.substances_or_medication),
        ),
        (
            "Goals",
            ", ".join(
                item.value or ""
                for item in record.goals.therapy_goals
                if item.is_addressed()
            )
            or _value(record.goals.preferred_start),
        ),
    ]
    lines = ["Known:"]
    for label, value in known:
        lines.append(f"- {label}: {value or 'not yet established'}")

    safety_bits = []
    for label, evidence in (
        ("self-harm", record.safety.self_harm),
        ("harm to others", record.safety.harm_to_others),
        ("medical urgency", record.safety.medical_urgency),
    ):
        safety_bits.append(f"{label}: {_value(evidence) or 'not yet assessed'}")
    lines.append(f"- Safety: {'; '.join(safety_bits)}")

    if completeness:
        lines.append("")
        lines.append("Open required items:")
        if completeness.missing_required_items:
            lines.extend(f"- {item}" for item in completeness.missing_required_items)
        else:
            lines.append("- none")

    return "\n".join(lines)
