from psychoanalyst_app.agents.intake.record_completeness import (
    intake_record_completion_decision,
    missing_items_from_record,
)
from psychoanalyst_app.agents.intake.slots import MAX_INTAKE_PATIENT_TURNS
from psychoanalyst_app.models.intake_record import IntakeEvidence, IntakeRecord


def _evidence(value: str, *, status: str = "informative") -> IntakeEvidence:
    return IntakeEvidence(
        value=value,
        evidence_quote=value,
        source_role="user",
        source_message_index=1,
        response_status=status,  # type: ignore[arg-type]
        direct_ask=status != "informative",
    )


def test_empty_record_misses_all_hard_items() -> None:
    diagnostics = missing_items_from_record(IntakeRecord())

    assert diagnostics.missing_hard_items == [
        "risk_screen",
        "presenting_problem",
        "duration",
        "functional_impairment",
        "goal_preference",
    ]
    assert diagnostics.next_required_item == "risk_screen"


def test_unknown_after_direct_ask_is_addressed_not_informative() -> None:
    record = IntakeRecord()
    record.presenting_problem.time_course.duration_or_onset = _evidence(
        "I do not know",
        status="unknown",
    )

    diagnostics = missing_items_from_record(record)

    assert "duration" in diagnostics.missing_hard_items
    assert "duration" in diagnostics.addressed_hard_items
    assert "duration" in diagnostics.unable_to_answer_items


def test_max_turn_completion_allows_addressed_hard_items_with_missing_soft() -> None:
    record = IntakeRecord()
    record.presenting_problem.main_concern = _evidence("anxiety")
    record.presenting_problem.time_course.duration_or_onset = _evidence(
        "I do not know",
        status="unknown",
    )
    record.presenting_problem.functional_impairment = _evidence("work impact")
    record.goals.therapy_goals = [_evidence("sleep better")]
    record.safety.self_harm = _evidence("denied")
    record.safety.harm_to_others = _evidence("denied")
    record.safety.medical_urgency = _evidence("denied")

    diagnostics = intake_record_completion_decision(
        record,
        patient_turn_count=MAX_INTAKE_PATIENT_TURNS,
    )

    assert diagnostics.complete
    assert diagnostics.max_turn_completion
    assert "duration" in diagnostics.missing_hard_items


def test_max_turn_completion_rejects_unasked_missing_hard_items() -> None:
    record = IntakeRecord()
    record.presenting_problem.main_concern = _evidence("anxiety")

    diagnostics = intake_record_completion_decision(
        record,
        patient_turn_count=MAX_INTAKE_PATIENT_TURNS,
    )

    assert not diagnostics.complete
    assert "risk_screen" in diagnostics.missing_hard_items


def test_combined_safety_denial_completes_risk_screen() -> None:
    quote = (
        "I have not had thoughts of harming myself or anyone else. "
        "The chest tightness is not medically urgent."
    )
    record = IntakeRecord()
    record.safety.self_harm = _evidence("denied")
    record.safety.self_harm.evidence_quote = quote
    record.safety.harm_to_others = _evidence("denied")
    record.safety.harm_to_others.evidence_quote = quote
    record.safety.medical_urgency = _evidence("denied")
    record.safety.medical_urgency.evidence_quote = quote

    diagnostics = missing_items_from_record(record)

    assert "risk_screen" not in diagnostics.missing_hard_items
