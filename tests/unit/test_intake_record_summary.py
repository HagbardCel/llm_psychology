from psychoanalyst_app.agents.intake.record_summary import (
    UNANSWERED_SECTION_HEADING,
    summarize_intake_record_for_prompt,
)
from psychoanalyst_app.models.intake_record import IntakeEvidence, IntakeRecord


def _informative(
    value: str,
    *,
    index: int = 1,
) -> IntakeEvidence:
    return IntakeEvidence(
        value=value,
        evidence_quote=value,
        source_role="user",
        source_message_index=index,
    )


def _unknown(
    *,
    quote: str = "I don't know",
    value: str | None = "I don't know",
    index: int = 2,
) -> IntakeEvidence:
    return IntakeEvidence(
        value=value,
        evidence_quote=quote,
        source_role="user",
        source_message_index=index,
        response_status="unknown",
        direct_ask=True,
    )


def test_unknown_duration_does_not_leak_into_known() -> None:
    record = IntakeRecord()
    record.presenting_problem.time_course.duration_or_onset = _unknown()

    summary = summarize_intake_record_for_prompt(record)

    assert "I don't know" not in summary.split(UNANSWERED_SECTION_HEADING)[0]
    assert "- Time course: not yet established" in summary


def test_unknown_duration_appears_under_asked_but_unanswered() -> None:
    record = IntakeRecord()
    record.presenting_problem.time_course.duration_or_onset = _unknown()

    summary = summarize_intake_record_for_prompt(record)

    assert UNANSWERED_SECTION_HEADING in summary
    assert "- Time course: patient could not answer" in summary


def test_label_consistency_between_sections() -> None:
    record = IntakeRecord()
    record.presenting_problem.time_course.duration_or_onset = _unknown()

    summary = summarize_intake_record_for_prompt(record)

    assert "- Time course: not yet established" in summary
    assert summary.count("- Time course:") == 2


def test_informative_main_concern_only_under_known() -> None:
    record = IntakeRecord()
    record.presenting_problem.main_concern = _informative("anxiety")

    summary = summarize_intake_record_for_prompt(record)

    assert "- Main concern: anxiety" in summary
    assert UNANSWERED_SECTION_HEADING not in summary


def test_empty_field_does_not_create_unanswered_line() -> None:
    summary = summarize_intake_record_for_prompt(IntakeRecord())

    assert "- Main concern: not yet established" in summary
    assert UNANSWERED_SECTION_HEADING not in summary


def test_unknown_goal_list_item_not_listed_as_goal() -> None:
    record = IntakeRecord()
    record.goals.therapy_goals = [_unknown(quote="not sure", value="not sure")]

    summary = summarize_intake_record_for_prompt(record)

    known_section = summary.split(UNANSWERED_SECTION_HEADING)[0]
    assert "not sure" not in known_section
    assert "- Goals: not yet established" in known_section
    assert summary.count("- Goals:") == 2


def test_multiple_unknown_goals_emit_one_unanswered_line() -> None:
    record = IntakeRecord()
    record.goals.therapy_goals = [
        _unknown(quote="not sure", value="not sure", index=2),
        _unknown(quote="I don't know", value="I don't know", index=3),
    ]

    summary = summarize_intake_record_for_prompt(record)

    unanswered = summary.split(UNANSWERED_SECTION_HEADING, 1)[1]
    assert unanswered.count("- Goals:") == 1


def test_informative_coping_and_goal_list_items_appear() -> None:
    record = IntakeRecord()
    record.coping.attempted_strategies = [_informative("exercise")]
    record.goals.therapy_goals = [_informative("sleep better")]

    summary = summarize_intake_record_for_prompt(record)

    assert "- Coping: exercise" in summary
    assert "- Goals: sleep better" in summary
    assert UNANSWERED_SECTION_HEADING not in summary


def test_empty_asked_but_unanswered_section_is_omitted() -> None:
    record = IntakeRecord()
    record.presenting_problem.main_concern = _informative("anxiety")

    summary = summarize_intake_record_for_prompt(record)

    assert UNANSWERED_SECTION_HEADING not in summary


def test_safety_unanswered_uses_explicit_labels() -> None:
    record = IntakeRecord()
    record.safety.self_harm = _unknown(quote="I don't know")

    summary = summarize_intake_record_for_prompt(record)

    assert "- Self-harm risk: patient could not answer" in summary
    assert "Self-harm risk: not yet assessed" in summary
