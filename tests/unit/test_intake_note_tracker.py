from datetime import datetime

import pytest

from psychoanalyst_app.agents.intake.note_tracker import extract_intake_record_patch
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import IntakeRecord, IntakeRecordPatch
from psychoanalyst_app.services.llm_phases import INTAKE_NOTE_TRACKING

pytestmark = [pytest.mark.trio, pytest.mark.unit]


class _LLM:
    def __init__(self) -> None:
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
        return IntakeRecordPatch(no_new_information=True)


async def test_note_tracker_uses_patch_schema_phase_and_messages() -> None:
    llm = _LLM()

    patch = await extract_intake_record_patch(
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

    assert patch == IntakeRecordPatch(no_new_information=True)
    assert llm.schema is IntakeRecordPatch
    assert llm.phase == INTAKE_NOTE_TRACKING
    assert "How long has this been happening?" in llm.prompt
    assert "No, I do not know." in llm.prompt
    assert "3" in llm.prompt
