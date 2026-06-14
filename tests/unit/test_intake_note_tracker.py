from datetime import datetime

import pytest

from psychoanalyst_app.agents.intake.note_tracker import (
    extract_intake_record_patch,
)
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
    PresentingProblemRecord,
)
from psychoanalyst_app.services.llm_phases import INTAKE_NOTE_TRACKING

pytestmark = [pytest.mark.trio, pytest.mark.unit]


class _LLM:
    def __init__(self, output) -> None:
        self.output = output
        self.prompt = ""
        self.phase = None
        self.schema = None

    async def generate_structured_output_async(
        self,
        prompt,
        schema,
        *,
        method="json_schema",
        phase,
    ):
        _ = method
        self.prompt = prompt
        self.phase = phase
        self.schema = schema
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


async def test_note_tracker_uses_patch_schema_phase_and_messages() -> None:
    llm = _LLM(IntakeRecordPatch(no_new_information=True))

    result = await extract_intake_record_patch(
        llm_service=llm,
        current_record=IntakeRecord(),
        latest_user_message=Message(
            role="user",
            content="No, I do not know.",
            timestamp=datetime.now(),
        ),
        previous_assistant_message=Message(
            role="assistant",
            content="How long has this been happening?",
            timestamp=datetime.now(),
        ),
        source_message_index=3,
    )

    assert result.status == "no_new_information"
    assert result.patch is None
    assert llm.schema is IntakeRecordPatch
    assert llm.phase == INTAKE_NOTE_TRACKING
    assert "How long has this been happening?" in llm.prompt
    assert "No, I do not know." in llm.prompt
    assert "3" in llm.prompt


async def test_note_tracker_validates_dict_output() -> None:
    llm = _LLM(
        {
            "presenting_problem": {
                "main_concern": {
                    "value": "anxiety",
                    "evidence_quote": "I feel anxious every day",
                    "source_message_index": 2,
                    "source_role": "user",
                    "confidence": "high",
                }
            }
        }
    )

    result = await extract_intake_record_patch(
        llm_service=llm,
        current_record=IntakeRecord(),
        latest_user_message=Message(
            role="user",
            content="I feel anxious every day",
            timestamp=datetime.now(),
        ),
        previous_assistant_message=None,
        source_message_index=2,
    )

    assert result.status == "success"
    assert result.patch == IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="anxiety",
                evidence_quote="I feel anxious every day",
                source_message_index=2,
                source_role="user",
                confidence="high",
            )
        )
    )


async def test_note_tracker_reports_invalid_output() -> None:
    result = await extract_intake_record_patch(
        llm_service=_LLM("not a patch"),
        current_record=IntakeRecord(),
        latest_user_message=Message(
            role="user",
            content="I feel anxious every day",
            timestamp=datetime.now(),
        ),
        previous_assistant_message=None,
        source_message_index=2,
    )

    assert result.status == "invalid_patch"
    assert result.error_code == "unexpected_output_type"


async def test_note_tracker_reports_llm_failure() -> None:
    result = await extract_intake_record_patch(
        llm_service=_LLM(RuntimeError("boom")),
        current_record=IntakeRecord(),
        latest_user_message=Message(
            role="user",
            content="I feel anxious every day",
            timestamp=datetime.now(),
        ),
        previous_assistant_message=None,
        source_message_index=2,
    )

    assert result.status == "llm_failure"
    assert result.error_code == "RuntimeError"
