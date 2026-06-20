"""Prompt summaries for structured intake records.

Unknown/unable evidence is workflow/completeness state, not a known clinical fact.
"""

from __future__ import annotations

from psychoanalyst_app.agents.intake.record_completeness import IntakeCompleteness
from psychoanalyst_app.models.intake_record import IntakeEvidence, IntakeRecord

KNOWN_SECTION_HEADING = "Known:"
UNANSWERED_SECTION_HEADING = "Asked but unanswered:"
_UNANSWERED_NOTE = "patient could not answer"
_EMPTY_KNOWN = "not yet established"
_EMPTY_SAFETY = "not yet assessed"

_SAFETY_FIELDS = (
    ("Self-harm risk", "self_harm"),
    ("Harm-to-others risk", "harm_to_others"),
    ("Medical urgency", "medical_urgency"),
)


def _known_value(evidence: IntakeEvidence) -> str | None:
    if evidence.is_present():
        return evidence.value
    return None


def _known_line(label: str, value: str | None, *, empty: str = _EMPTY_KNOWN) -> str:
    return f"- {label}: {value or empty}"


def _unanswered_line(label: str) -> str:
    return f"- {label}: {_UNANSWERED_NOTE}"


def _time_course_known(record: IntakeRecord) -> str | None:
    time_course = record.presenting_problem.time_course
    for evidence in (
        time_course.duration_or_onset,
        time_course.frequency,
    ):
        if value := _known_value(evidence):
            return value
    return None


def _time_course_unanswered(record: IntakeRecord) -> bool:
    if _time_course_known(record) is not None:
        return False
    time_course = record.presenting_problem.time_course
    return any(
        evidence.is_unable_or_unknown()
        for evidence in (
            time_course.duration_or_onset,
            time_course.frequency,
        )
    )


def _list_present_values(items: list[IntakeEvidence]) -> str | None:
    values = [item.value for item in items if item.is_present() and item.value]
    if not values:
        return None
    return ", ".join(values)


def _section_unanswered(
    *,
    present_value: str | None,
    list_items: list[IntakeEvidence],
    scalar: IntakeEvidence,
) -> bool:
    if present_value is not None:
        return False
    if scalar.is_unable_or_unknown():
        return True
    return any(item.is_unable_or_unknown() for item in list_items)


def summarize_intake_record_for_prompt(
    record: IntakeRecord,
    completeness: IntakeCompleteness | None = None,
) -> str:
    """Return a compact text summary suitable for the intake response prompt."""
    known_lines = [KNOWN_SECTION_HEADING]
    unanswered_lines: list[str] = []

    known_lines.append(
        _known_line(
            "Main concern",
            _known_value(record.presenting_problem.main_concern),
        )
    )
    if record.presenting_problem.main_concern.is_unable_or_unknown():
        unanswered_lines.append(_unanswered_line("Main concern"))

    known_lines.append(_known_line("Time course", _time_course_known(record)))
    if _time_course_unanswered(record):
        unanswered_lines.append(_unanswered_line("Time course"))

    known_lines.append(
        _known_line("Sleep", _known_value(record.presenting_problem.sleep_impact))
    )
    if record.presenting_problem.sleep_impact.is_unable_or_unknown():
        unanswered_lines.append(_unanswered_line("Sleep"))

    known_lines.append(
        _known_line(
            "Functional impact",
            _known_value(record.presenting_problem.functional_impairment),
        )
    )
    if record.presenting_problem.functional_impairment.is_unable_or_unknown():
        unanswered_lines.append(_unanswered_line("Functional impact"))

    coping_known = _list_present_values(record.coping.attempted_strategies)
    if coping_known is None:
        coping_known = _known_value(record.coping.substances_or_medication)
    known_lines.append(_known_line("Coping", coping_known))
    if _section_unanswered(
        present_value=coping_known,
        list_items=record.coping.attempted_strategies,
        scalar=record.coping.substances_or_medication,
    ):
        unanswered_lines.append(_unanswered_line("Coping"))

    goals_known = _list_present_values(record.goals.therapy_goals)
    if goals_known is None:
        goals_known = _known_value(record.goals.preferred_start)
    known_lines.append(_known_line("Goals", goals_known))
    if _section_unanswered(
        present_value=goals_known,
        list_items=record.goals.therapy_goals,
        scalar=record.goals.preferred_start,
    ):
        unanswered_lines.append(_unanswered_line("Goals"))

    safety_bits = []
    for label, attr in _SAFETY_FIELDS:
        evidence = getattr(record.safety, attr)
        safety_bits.append(f"{label}: {_known_value(evidence) or _EMPTY_SAFETY}")
        if evidence.is_unable_or_unknown():
            unanswered_lines.append(_unanswered_line(label))
    known_lines.append(f"- Safety: {'; '.join(safety_bits)}")

    lines = known_lines
    if unanswered_lines:
        lines.extend(["", UNANSWERED_SECTION_HEADING, *unanswered_lines])

    if completeness:
        lines.extend(["", "Open required items:"])
        if completeness.missing_required_items:
            lines.extend(f"- {item}" for item in completeness.missing_required_items)
        else:
            lines.append("- none")

    return "\n".join(lines)
