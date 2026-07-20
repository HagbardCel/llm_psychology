"""API-boundary resilience integration tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.api.contracts import RetryOperationRequest
from jung.client.api_client import ClientSettings, JungApiClient
from jung.domain.models import ChatTurnStatus, OperationStatus
from jung.llm.errors import LLMTimeout
from jung.llm.fake import FailureExpectation, FakeLLM, StructuredExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from tests.integration.jung.application_fixtures import assessment_result
from tests.integration.jung.resilience_support import (
    assert_styles_equivalent,
    count_assessment_operations,
    count_chat_turns_for_session,
    expected_style_options_response,
    style_selection_projection,
    wait_for_health,
    wait_for_snapshot,
)
from tests.integration.jung.scenarios import complete_intake_for_assessment, open_intake
from tests.jung_api_fixtures import (
    RecordingFakeLLM,
    create_test_api_app,
    run_uvicorn_api,
)

pytestmark = pytest.mark.asyncio


async def test_assessment_failure_retry_preserves_operation_identity(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    recording = RecordingFakeLLM(
        FakeLLM(
            [
                FailureExpectation(
                    task=LLMTask.ASSESSMENT,
                    error=LLMTimeout("timeout"),
                ),
                StructuredExpectation(
                    task=LLMTask.ASSESSMENT,
                    output_type=AssessmentResult,
                    response=assessment_result(),
                ),
            ]
        )
    )
    test_app = create_test_api_app(store=store, fake_llm=recording)

    async with run_uvicorn_api(test_app.app) as (http_base, _ws_url):
        async with JungApiClient(ClientSettings(http_base)) as client:
            await wait_for_health(client)
            failed = await wait_for_snapshot(
                client,
                predicate=lambda snapshot: (
                    snapshot.operation is not None
                    and snapshot.operation.status == "failed"
                ),
                description="assessment operation to fail",
            )
            assert failed.operation is not None
            assert failed.operation.id == operation_id
            assert failed.operation.error is not None
            assert failed.operation.error.retryable is True
            assert "retry_operation" in failed.available_commands

            retry_snapshot = await client.retry_current_operation(
                RetryOperationRequest(expected_revision=failed.revision),
            )
            assert retry_snapshot.revision > failed.revision
            if retry_snapshot.operation is not None:
                assert retry_snapshot.operation.id == operation_id

            completed = await wait_for_snapshot(
                client,
                predicate=lambda snapshot: snapshot.stage == "style_selection",
                description="assessment retry to complete",
            )
            assert completed.stage == "style_selection"

    assert recording.recorded_tasks == (
        LLMTask.ASSESSMENT,
        LLMTask.ASSESSMENT,
    )
    recording.assert_exhausted()
    inspection = SQLiteStore(test_app.store_path)
    operation = inspection.get_operation(operation_id)
    assert operation is not None
    assert operation.id == operation_id
    assert operation.status is OperationStatus.COMPLETE
    assert count_assessment_operations(inspection, intake_id) == 1


async def test_completed_work_survives_server_restart_without_recomputation(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    server_a_recording = RecordingFakeLLM(
        FakeLLM(
            [
                StructuredExpectation(
                    task=LLMTask.ASSESSMENT,
                    output_type=AssessmentResult,
                    response=assessment_result(),
                )
            ]
        )
    )
    server_a = create_test_api_app(store=store, fake_llm=server_a_recording)

    async with run_uvicorn_api(server_a.app) as (http_base_a, _ws_url):
        async with JungApiClient(ClientSettings(http_base_a)) as client_a:
            await wait_for_health(client_a)
            snapshot_a = await wait_for_snapshot(
                client_a,
                predicate=lambda snapshot: snapshot.stage == "style_selection",
                description="assessment to complete on server A",
            )
            styles_a = await client_a.get_styles()
            revision_a = snapshot_a.revision

    assert server_a_recording.recorded_tasks == (LLMTask.ASSESSMENT,)
    server_a_recording.assert_exhausted()

    server_b_recording = RecordingFakeLLM(FakeLLM(()))
    server_b = create_test_api_app(store=store, fake_llm=server_b_recording)

    async with run_uvicorn_api(server_b.app) as (http_base_b, _ws_url):
        async with JungApiClient(ClientSettings(http_base_b)) as client_b:
            await wait_for_health(client_b)
            snapshot_b = await client_b.get_state()
            styles_b = await client_b.get_styles()

    assert style_selection_projection(snapshot_b) == style_selection_projection(
        snapshot_a
    )
    assert snapshot_b.revision >= revision_a
    assert_styles_equivalent(styles_b, styles_a)
    assert server_b_recording.recorded_tasks == ()
    server_b_recording.assert_exhausted()


async def test_stale_running_operation_recovers_on_startup(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    initial_revision = store.get_app_state().revision
    recording = RecordingFakeLLM(
        FakeLLM(
            [
                StructuredExpectation(
                    task=LLMTask.ASSESSMENT,
                    output_type=AssessmentResult,
                    response=assessment_result(),
                )
            ]
        )
    )
    test_app = create_test_api_app(store=store, fake_llm=recording)

    async with run_uvicorn_api(test_app.app) as (http_base, _ws_url):
        async with JungApiClient(ClientSettings(http_base)) as client:
            await wait_for_health(client)
            snapshot = await wait_for_snapshot(
                client,
                predicate=lambda item: item.stage == "style_selection",
                description="stale operation recovery",
            )
            assert snapshot.revision > initial_revision
            styles = await client.get_styles()
            assert_styles_equivalent(styles, expected_style_options_response())

    assert recording.recorded_tasks == (LLMTask.ASSESSMENT,)
    recording.assert_exhausted()
    inspection = SQLiteStore(test_app.store_path)
    operation = inspection.get_operation(operation_id)
    assert operation is not None
    assert operation.id == operation_id
    assert operation.status is OperationStatus.COMPLETE
    assert count_assessment_operations(inspection, intake_id) == 1


async def test_stale_pending_chat_turn_failed_in_place_without_replacement(
    store: SQLiteStore,
) -> None:
    session_id, now = open_intake(store)
    turn_id = uuid4()
    client_message_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
        user_message_id=uuid4(),
        content="hello",
        now=now,
    )
    initial_turn_count = count_chat_turns_for_session(store, session_id)
    assert initial_turn_count == 1
    initial_revision = store.get_app_state().revision

    recording = RecordingFakeLLM(FakeLLM(()))
    test_app = create_test_api_app(store=store, fake_llm=recording)

    async with run_uvicorn_api(test_app.app) as (http_base, _ws_url):
        async with JungApiClient(ClientSettings(http_base)) as client:
            await wait_for_health(client)
            snapshot = await client.get_state()
            assert snapshot.active_chat_turn is None
            assert snapshot.revision > initial_revision
            history = await client.get_session(session_id)
            user_messages = [
                message
                for message in history.messages
                if message.role == "user"
                and message.client_message_id == client_message_id
            ]
            assistant_messages = [
                message
                for message in history.messages
                if message.role == "assistant"
                and message.client_message_id == client_message_id
            ]
            assert len(user_messages) == 1
            assert len(assistant_messages) == 0

    assert recording.recorded_tasks == ()
    recording.assert_exhausted()
    inspection = SQLiteStore(test_app.store_path)
    final_turn_count = count_chat_turns_for_session(inspection, session_id)
    assert final_turn_count == initial_turn_count == 1
    turn_by_id = inspection.get_chat_turn(turn_id)
    turn_by_client = inspection.get_chat_turn_by_client_id(
        session_id,
        client_message_id,
    )
    assert turn_by_id is not None
    assert turn_by_client is not None
    assert turn_by_client.id == turn_by_id.id == turn_id
    assert turn_by_id.status is ChatTurnStatus.FAILED
    assert turn_by_id.error_code == "stale_pending"
    assert turn_by_id.retryable is True
    assert turn_by_id.error_message
