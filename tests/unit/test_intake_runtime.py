from psychoanalyst_app.agents.intake.note_tracker import (
    IntakePatchExtractionResult,
)
from psychoanalyst_app.agents.intake.record_completeness import IntakeCompleteness
from psychoanalyst_app.agents.intake.runtime import (
    IntakeRecordState,
    intake_record_metadata,
)
from psychoanalyst_app.models.intake_record import IntakeRecord, IntakeRecordPatch


def test_successful_note_tracking_without_merge_result_is_not_plain_success() -> None:
    metadata = intake_record_metadata(
        IntakeRecordState(
            record=IntakeRecord(),
            completeness=IntakeCompleteness(complete=False),
            note_tracking_enabled=True,
            note_tracking=IntakePatchExtractionResult(
                status="success",
                patch=IntakeRecordPatch(),
            ),
            merge_result=None,
            should_emit_metadata=True,
        ),
        legacy_diagnostics={},
    )

    tracking = metadata["intake_note_tracking"]
    assert tracking["status"] == "merge_not_run"
    assert tracking["raw_extraction_status"] == "success"
    assert metadata["intake_record_persistence"] == {
        "should_persist": False,
        "record_changed": False,
    }
