from datetime import datetime

import pytest

from psychoanalyst_app.agents.note_taker.intake_patch import (
    extract_intake_record_patch,
)
from psychoanalyst_app.exceptions import LLMServiceError
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
        **kwargs,
    ):
        _ = method, kwargs
        self.prompt = prompt
        self.phase = phase
        self.schema = schema
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


async def test_extract_intake_record_patch_uses_prompt_formatter(monkeypatch) -> None:
    sentinel = "FORMATTED_PROMPT_SENTINEL"

    def _fake_formatter(**_kwargs):
        return sentinel

    monkeypatch.setattr(
        "psychoanalyst_app.agents.note_taker.intake_patch.format_intake_note_tracking_prompt",
        _fake_formatter,
    )
    llm = _LLM(IntakeRecordPatch(no_new_information=True))

    await extract_intake_record_patch(
        llm_service=llm,
        current_record=IntakeRecord(),
        latest_user_message=Message(
            role="user",
            content="No, I do not know.",
            timestamp=datetime.now(),
        ),
        previous_assistant_message=None,
        source_message_index=3,
    )

    assert llm.prompt == sentinel


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


async def test_note_tracker_reports_invalid_dict_output() -> None:
    result = await extract_intake_record_patch(
        llm_service=_LLM({"presenting_problem": {"main_concern": {"value": 123}}}),
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
    assert result.error_code == "ValidationError"
    assert result.error_message




async def test_note_tracker_rejects_conflicting_no_new_information() -> None:
    llm = _LLM(
        IntakeRecordPatch(
            no_new_information=True,
            presenting_problem=PresentingProblemRecord(
                main_concern=IntakeEvidence(
                    value="anxiety",
                    evidence_quote="I feel anxious every day",
                    source_role="user",
                    source_message_index=2,
                )
            ),
        )
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

    assert result.status == "invalid_patch"
    assert result.error_code == "conflicting_no_new_information"


async def test_note_tracker_forwards_llm_service_error_diagnostics() -> None:
    result = await extract_intake_record_patch(
        llm_service=_LLM(
            LLMServiceError(
                "parse failed",
                metadata={
                    "phase": "intake_note_tracking",
                    "schema_name": "IntakeRecordPatch",
                    "provider": "local",
                    "model_name": "fake",
                    "parse_error_type": "JSONDecodeError",
                    "parse_error": "Expecting value",
                },
            )
        ),
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
    assert result.error_code == "LLMServiceError"
    assert "phase=intake_note_tracking" in result.error_message
    assert "parse_error=Expecting value" in result.error_message


async def test_note_tracker_reports_timeout() -> None:
    import time

    import trio

    class _BlockingSlowLLM:
        def generate_structured_output(self, *_args, **_kwargs):
            time.sleep(5)
            return IntakeRecordPatch()

        async def generate_structured_output_async(self, *args, **kwargs):
            return await trio.to_thread.run_sync(
                lambda: self.generate_structured_output(*args, **kwargs),
                abandon_on_cancel=kwargs.get("abandon_on_cancel", False),
            )

    result = await extract_intake_record_patch(
        llm_service=_BlockingSlowLLM(),
        current_record=IntakeRecord(),
        latest_user_message=Message(
            role="user",
            content="I feel anxious every day",
            timestamp=datetime.now(),
        ),
        previous_assistant_message=None,
        source_message_index=2,
        timeout_seconds=0.05,
    )

    assert result.status == "timeout"
    assert result.error_code == "timeout"


async def test_note_tracker_propagates_cancellation() -> None:
    import trio

    class _WaitingLLM:
        async def generate_structured_output_async(
            self,
            _prompt,
            _schema,
            method="json_schema",
            *,
            phase,
            **kwargs,
        ):
            _ = method, phase, kwargs
            await trio.sleep_forever()

    with trio.CancelScope() as cancel_scope:
        async with trio.open_nursery() as nursery:

            async def cancel_soon() -> None:
                await trio.sleep(0)
                cancel_scope.cancel()

            nursery.start_soon(cancel_soon)
            with pytest.raises(trio.Cancelled):
                await extract_intake_record_patch(
                    llm_service=_WaitingLLM(),
                    current_record=IntakeRecord(),
                    latest_user_message=Message(
                        role="user",
                        content="I feel anxious every day",
                        timestamp=datetime.now(),
                    ),
                    previous_assistant_message=None,
                    source_message_index=2,
                )
