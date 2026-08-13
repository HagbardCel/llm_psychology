"""Composition tests for session/supervisor LLM role ownership and wiring."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from jung.composition import application_context
from jung.diagnostics import DiagnosticRecorder
from jung.domain.commands import (
    EndSession,
    SelectStyle,
    SendMessage,
    UpdateProfile,
)
from jung.domain.models import Profile, Stage
from jung.domain.results import ChatCompleted
from jung.llm.gateway import AdapterConfig, LLMTask
from jung.llm.openai_compatible import OpenAICompatibleLLM
from jung.phases.assessment.models import AssessmentResult
from jung.phases.intake.models import IntakeRecordPatch
from tests.integration.application.application_fixtures import (
    assessment_result,
    collect_stream,
    completing_intake_patch,
    post_session_expectations,
    wait_for_stage,
)
from tests.support.fake_llm import (
    FakeLLM,
    RecordingFakeLLM,
    StreamExpectation,
    StructuredExpectation,
)
from tests.support.settings import make_test_settings

pytestmark = pytest.mark.asyncio


async def test_default_config_builds_two_distinct_adapters(
    tmp_path: Path,
) -> None:
    configs: list[AdapterConfig] = []
    instances: list[object] = []

    def factory(
        config: AdapterConfig,
        recorder: DiagnosticRecorder | None,
    ) -> OpenAICompatibleLLM:
        del recorder
        configs.append(config)
        llm = FakeLLM([])
        instances.append(llm)
        return llm  # type: ignore[return-value]

    settings = make_test_settings(
        data_dir=tmp_path,
        model_name="shared-model",
        llm_base_url="http://shared.test/v1",
        llm_api_key="shared-key",
    )
    async with application_context(settings, llm_factory=factory):
        pass

    assert len(configs) == 2
    assert configs[0].base_url == configs[1].base_url == "http://shared.test/v1"
    assert configs[0].api_key == configs[1].api_key == "shared-key"
    assert instances[0] is not instances[1]


async def test_split_endpoint_reaches_adapters(
    tmp_path: Path,
) -> None:
    configs: list[AdapterConfig] = []

    def factory(
        config: AdapterConfig,
        recorder: DiagnosticRecorder | None,
    ) -> OpenAICompatibleLLM:
        del recorder
        configs.append(config)
        return FakeLLM([])  # type: ignore[return-value]

    settings = make_test_settings(
        data_dir=tmp_path,
        llm_base_url="http://session.test/v1",
        model_name="session-model",
        supervisor_llm_base_url="http://supervisor.test/v1",
        supervisor_model_name="supervisor-model",
    )
    async with application_context(settings, llm_factory=factory) as application:
        await application.get_snapshot()

    assert configs[0].base_url == "http://session.test/v1"
    assert configs[1].base_url == "http://supervisor.test/v1"


async def test_supervisor_adapter_inherits_session_endpoint_options(
    tmp_path: Path,
) -> None:
    configs: list[AdapterConfig] = []

    def factory(
        config: AdapterConfig,
        recorder: DiagnosticRecorder | None,
    ) -> OpenAICompatibleLLM:
        del recorder
        configs.append(config)
        return FakeLLM([])  # type: ignore[return-value]

    settings = make_test_settings(
        data_dir=tmp_path,
        llm_api_key="session-secret",
        llm_default_headers={"X-Session": "yes"},
        llm_extra_body={"thinking": False},
    )
    async with application_context(settings, llm_factory=factory):
        pass

    session_config, supervisor_config = configs
    assert supervisor_config.api_key == "session-secret"
    assert supervisor_config.default_headers == {"X-Session": "yes"}
    assert supervisor_config.extra_body == {"thinking": False}
    assert session_config.api_key == supervisor_config.api_key


async def test_supervisor_adapter_explicit_clear_does_not_inherit(
    tmp_path: Path,
) -> None:
    configs: list[AdapterConfig] = []

    def factory(
        config: AdapterConfig,
        recorder: DiagnosticRecorder | None,
    ) -> OpenAICompatibleLLM:
        del recorder
        configs.append(config)
        return FakeLLM([])  # type: ignore[return-value]

    settings = make_test_settings(
        data_dir=tmp_path,
        llm_api_key="session-secret",
        llm_default_headers={"X-Session": "yes"},
        llm_extra_body={"thinking": False},
        supervisor_llm_api_key="",
        supervisor_llm_default_headers={},
        supervisor_llm_extra_body={},
        llm_task_config=json.dumps(
            {
                "assessment": {"extra_body": {"task_only": True}},
            }
        ),
    )
    async with application_context(settings, llm_factory=factory):
        pass

    _, supervisor_config = configs
    assert supervisor_config.api_key == ""
    assert supervisor_config.default_headers == {}
    assert supervisor_config.extra_body == {}
    assert supervisor_config.task_extra_body == {
        LLMTask.ASSESSMENT: {"task_only": True}
    }


async def test_supervisor_adapter_override_values(
    tmp_path: Path,
) -> None:
    configs: list[AdapterConfig] = []

    def factory(
        config: AdapterConfig,
        recorder: DiagnosticRecorder | None,
    ) -> OpenAICompatibleLLM:
        del recorder
        configs.append(config)
        return FakeLLM([])  # type: ignore[return-value]

    settings = make_test_settings(
        data_dir=tmp_path,
        llm_api_key="session-secret",
        llm_default_headers={"X-Session": "yes"},
        llm_extra_body={"thinking": False},
        supervisor_llm_api_key="supervisor-secret",
        supervisor_llm_default_headers={"X-Supervisor": "1"},
        supervisor_llm_extra_body={"mode": "strict"},
    )
    async with application_context(settings, llm_factory=factory):
        pass

    session_config, supervisor_config = configs
    assert session_config.api_key == "session-secret"
    assert supervisor_config.api_key == "supervisor-secret"
    assert supervisor_config.default_headers == {"X-Supervisor": "1"}
    assert supervisor_config.extra_body == {"mode": "strict"}


async def test_lifecycle_routes_tasks_to_role_gateways(
    tmp_path: Path,
) -> None:
    turn_messages = ("first turn", "second turn", "third turn")
    final_message_sequence = 5
    session_expectations: list[StructuredExpectation | StreamExpectation] = []
    for index, content in enumerate(turn_messages, start=1):
        if index < len(turn_messages):
            session_expectations.extend(
                [
                    StructuredExpectation(
                        task=LLMTask.INTAKE_PATCH,
                        output_type=IntakeRecordPatch,
                        response=IntakeRecordPatch(),
                    ),
                    StreamExpectation(
                        task=LLMTask.INTAKE_RESPONSE,
                        chunks=(f"Response {index}.",),
                    ),
                ]
            )
        else:
            session_expectations.extend(
                [
                    StructuredExpectation(
                        task=LLMTask.INTAKE_PATCH,
                        output_type=IntakeRecordPatch,
                        response=completing_intake_patch(
                            message_sequence=final_message_sequence,
                            quote=content,
                        ),
                    ),
                    StreamExpectation(
                        task=LLMTask.INTAKE_RESPONSE,
                        chunks=("Thank you for sharing.",),
                    ),
                ]
            )
    session_expectations.append(
        StreamExpectation(
            task=LLMTask.THERAPY_RESPONSE,
            chunks=("Let's explore that.",),
        )
    )

    supervisor_expectations: list[StructuredExpectation | StreamExpectation] = [
        StructuredExpectation(
            task=LLMTask.ASSESSMENT,
            output_type=AssessmentResult,
            response=assessment_result(),
        ),
        *post_session_expectations(),
    ]

    recorders: list[RecordingFakeLLM] = []

    def factory(
        config: AdapterConfig,
        recorder: DiagnosticRecorder | None,
    ) -> OpenAICompatibleLLM:
        del config, recorder
        if not recorders:
            recording = RecordingFakeLLM(FakeLLM(session_expectations))
        else:
            recording = RecordingFakeLLM(FakeLLM(supervisor_expectations))
        recorders.append(recording)
        return recording  # type: ignore[return-value]

    settings = make_test_settings(
        data_dir=tmp_path,
        model_name="session-model",
        supervisor_model_name="supervisor-model",
        llm_base_url="http://session.test/v1",
        supervisor_llm_base_url="http://supervisor.test/v1",
    )
    async with application_context(settings, llm_factory=factory) as application:
        await application.update_profile(
            UpdateProfile(
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session = (await application.get_snapshot()).active_session
        assert session is not None
        for content in turn_messages:
            items = await collect_stream(
                application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=uuid4(),
                    content=content,
                ),
            )
            assert isinstance(items[-1], ChatCompleted)
        await wait_for_stage(application, Stage.STYLE_SELECTION)
        await application.select_style(SelectStyle(style_id="cbt"))
        started = await application.start_session()
        items = await collect_stream(
            application,
            SendMessage(
                session_id=started.session.id,
                client_message_id=uuid4(),
                content="I slept badly again.",
            ),
        )
        assert isinstance(items[-1], ChatCompleted)
        await application.end_session(EndSession(session_id=started.session.id))
        await wait_for_stage(application, Stage.READY)

    session_recording, supervisor_recording = recorders
    session_tasks = set(session_recording.recorded_tasks)
    supervisor_tasks = set(supervisor_recording.recorded_tasks)

    assert session_tasks == {
        LLMTask.INTAKE_PATCH,
        LLMTask.INTAKE_RESPONSE,
        LLMTask.THERAPY_RESPONSE,
    }
    assert supervisor_tasks == {
        LLMTask.ASSESSMENT,
        LLMTask.POST_SESSION_ANALYSIS,
        LLMTask.POST_SESSION_UPDATE,
    }
    assert {model for _task, model in session_recording.recorded_calls} == {
        "session-model"
    }
    assert {model for _task, model in supervisor_recording.recorded_calls} == {
        "supervisor-model"
    }
    assert LLMTask.THERAPY_RESPONSE not in supervisor_tasks
    assert LLMTask.POST_SESSION_ANALYSIS not in session_tasks
    assert LLMTask.POST_SESSION_UPDATE not in session_tasks
    session_recording.assert_exhausted()
    supervisor_recording.assert_exhausted()
