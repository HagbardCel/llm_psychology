"""WebSocket integration tests against ephemeral Uvicorn."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from websockets.asyncio.client import connect as ws_connect

from jung.llm.errors import LLMUnavailable
from jung.llm.fake import (
    FailureExpectation,
    FakeLLM,
    StreamExpectation,
    StructuredExpectation,
)
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.intake.models import IntakeRecordPatch
from tests.integration.jung.application_fixtures import (
    completing_intake_patch,
    intake_message_expectations,
    post_session_expectations,
)
from tests.integration.jung.scenarios import advance_to_ready

pytestmark = pytest.mark.asyncio


async def _recv_json(ws, *, timeout: float = 15.0) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def _setup_intake_http(http_base: str) -> tuple[str, int]:
    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        revision = (await client.get("/api/v1/state")).json()["revision"]
        await client.put(
            "/api/v1/profile",
            json={
                "expected_revision": revision,
                "profile": {
                    "name": "Alex",
                    "primary_language": "English",
                    "date_of_birth": None,
                    "notes": None,
                },
            },
        )
        state = (await client.get("/api/v1/state")).json()
        session_id = state["active_session"]["id"]
        return session_id, state["revision"]


async def test_ready_websocket_handshake(uvicorn_api_urls) -> None:
    _http_base, ws_url = uvicorn_api_urls
    async with ws_connect(ws_url):
        return


async def test_invalid_then_valid_command_on_same_socket(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    fake_llm._expectations = list(intake_message_expectations("assistant reply"))
    session_id, revision = await _setup_intake_http(http_base)

    async with ws_connect(ws_url) as ws:
        await ws.send("not-json")
        err = await _recv_json(ws)
        assert err["type"] == "error"
        assert err["error"]["code"] == "validation_error"

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "session_id": session_id,
                    "client_message_id": str(uuid4()),
                    "request_id": str(uuid4()),
                    "expected_revision": revision,
                    "content": "hello",
                }
            )
        )
        saw_progress = False
        for _ in range(15):
            event = await _recv_json(ws)
            if event["type"] == "message_in_progress":
                saw_progress = True
                break
        assert saw_progress


async def test_non_final_intake_streaming_order(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    fake_llm._expectations = list(intake_message_expectations("Hello there"))
    session_id, revision = await _setup_intake_http(http_base)

    async with ws_connect(ws_url) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "session_id": session_id,
                    "client_message_id": str(uuid4()),
                    "request_id": str(uuid4()),
                    "expected_revision": revision,
                    "content": "I feel anxious.",
                }
            )
        )

        types: list[str] = []
        tokens: list[dict] = []
        completed: dict | None = None
        for _ in range(25):
            event = await _recv_json(ws)
            types.append(event["type"])
            if event["type"] == "token":
                tokens.append(event)
            if event["type"] == "message_completed":
                completed = event
                break

        assert "message_in_progress" in types
        assert "snapshot_changed" in types
        assert tokens
        sequences = [token["sequence"] for token in tokens]
        assert sequences == list(range(1, len(sequences) + 1))
        assert completed is not None
        joined = "".join(token["text"] for token in tokens)
        assert joined == completed["message"]["content"]


async def test_durable_chat_failure_sanitized_message(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    secret = "secret-marker"
    http_base, ws_url = uvicorn_api_urls
    fake_llm._expectations = [
        StructuredExpectation(
            task=LLMTask.INTAKE_PATCH,
            output_type=IntakeRecordPatch,
            response=IntakeRecordPatch(),
        ),
        FailureExpectation(
            task=LLMTask.INTAKE_RESPONSE,
            error=LLMUnavailable(secret),
        ),
    ]
    session_id, revision = await _setup_intake_http(http_base)

    async with ws_connect(ws_url) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "session_id": session_id,
                    "client_message_id": str(uuid4()),
                    "request_id": str(uuid4()),
                    "expected_revision": revision,
                    "content": "trigger failure",
                }
            )
        )
        error_event = None
        for _ in range(25):
            event = await _recv_json(ws)
            if event["type"] == "error":
                error_event = event
                break
        assert error_event is not None
        assert secret not in json.dumps(error_event)
        assert "language model" in error_event["error"]["message"].lower()


async def test_two_observers_receive_completion(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    fake_llm._expectations = list(intake_message_expectations("shared reply"))
    session_id, revision = await _setup_intake_http(http_base)
    command = {
        "type": "send_message",
        "session_id": session_id,
        "client_message_id": str(uuid4()),
        "request_id": str(uuid4()),
        "expected_revision": revision,
        "content": "hello both",
    }

    async with ws_connect(ws_url) as first, ws_connect(ws_url) as second:
        await first.send(json.dumps(command))

        async def wait_completed(ws) -> bool:
            for _ in range(25):
                event = await _recv_json(ws)
                if event["type"] == "message_completed":
                    return True
            return False

        first_done, second_done = await asyncio.gather(
            wait_completed(first),
            wait_completed(second),
        )
        assert first_done and second_done


async def test_http_end_session_reaches_websocket_observer(
    store: SQLiteStore,
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        now=ready.now,
    )
    revision = store.get_app_state().revision
    fake_llm._expectations = list(post_session_expectations())

    async with ws_connect(ws_url) as ws:
        await ws.send("not-json")
        warmup = await _recv_json(ws)
        assert warmup["type"] == "error"

        async with httpx.AsyncClient(base_url=http_base, timeout=15.0) as client:
            state = (await client.get("/api/v1/state")).json()
            assert state["active_session"]["id"] == str(therapy_id)
            response = await client.post(
                f"/api/v1/sessions/{therapy_id}/end",
                json={"expected_revision": revision},
            )
            assert response.status_code == 202
            assert response.json()["stage"] == "post_session"

        events: list[dict] = []
        for _ in range(25):
            try:
                events.append(await _recv_json(ws, timeout=2.0))
            except TimeoutError:
                break

        assert any(event.get("type") == "operation_changed" for event in events)
        assert any(
            event.get("type") == "snapshot_changed"
            or (
                event.get("type") == "operation_changed"
                and event.get("snapshot", {}).get("stage") == "post_session"
            )
            for event in events
        )


async def test_busy_rejects_second_message_while_generating(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    stream_gate = asyncio.Event()
    stream_started = asyncio.Event()

    class HoldingFakeLLM(FakeLLM):
        async def stream_text(self, messages, policy):
            stream_started.set()
            await stream_gate.wait()
            async for chunk in super().stream_text(messages, policy):
                yield chunk

    holding = HoldingFakeLLM(list(intake_message_expectations("first reply")))
    fake_llm._expectations = holding._expectations
    fake_llm.generate_structured = holding.generate_structured  # type: ignore[method-assign]
    fake_llm.stream_text = holding.stream_text  # type: ignore[method-assign]

    session_id, revision = await _setup_intake_http(http_base)

    async with ws_connect(ws_url) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "session_id": session_id,
                    "client_message_id": str(uuid4()),
                    "request_id": str(uuid4()),
                    "expected_revision": revision,
                    "content": "first",
                }
            )
        )
        await asyncio.wait_for(stream_started.wait(), timeout=5.0)
        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "session_id": session_id,
                    "client_message_id": str(uuid4()),
                    "request_id": str(uuid4()),
                    "expected_revision": revision,
                    "content": "second",
                }
            )
        )
        busy_event = None
        for _ in range(15):
            event = await _recv_json(ws)
            if event["type"] == "error" and event["error"]["code"] == "busy":
                busy_event = event
                break
        assert busy_event is not None
        stream_gate.set()


async def test_disconnect_during_generation_worker_completes_over_http(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    stream_gate = asyncio.Event()
    stream_started = asyncio.Event()

    class HoldingFakeLLM(FakeLLM):
        async def stream_text(self, messages, policy):
            stream_started.set()
            await stream_gate.wait()
            async for chunk in super().stream_text(messages, policy):
                yield chunk

    holding = HoldingFakeLLM(list(intake_message_expectations("completed offline")))
    fake_llm._expectations = holding._expectations
    fake_llm.generate_structured = holding.generate_structured  # type: ignore[method-assign]
    fake_llm.stream_text = holding.stream_text  # type: ignore[method-assign]

    session_id, revision = await _setup_intake_http(http_base)
    client_message_id = uuid4()

    async with ws_connect(ws_url) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "session_id": session_id,
                    "client_message_id": str(client_message_id),
                    "request_id": str(uuid4()),
                    "expected_revision": revision,
                    "content": "hello",
                }
            )
        )
        await asyncio.wait_for(stream_started.wait(), timeout=5.0)

    stream_gate.set()
    await asyncio.sleep(0.5)
    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        history = await client.get(f"/api/v1/sessions/{session_id}")
        assert history.status_code == 200
        roles = [message["role"] for message in history.json()["messages"]]
        assert "assistant" in roles


async def test_final_intake_schedules_assessment_operation(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    from jung.phases.assessment.models import AssessmentResult
    from tests.integration.jung.application_fixtures import assessment_result

    http_base, ws_url = uvicorn_api_urls
    turn_messages = ("first turn", "second turn", "third turn")
    final_message_sequence = 5
    expectations: list[StructuredExpectation | StreamExpectation] = []
    for index, content in enumerate(turn_messages, start=1):
        if index < len(turn_messages):
            expectations.extend(
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
            expectations.extend(
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
    expectations.append(
        StructuredExpectation(
            task=LLMTask.ASSESSMENT,
            output_type=AssessmentResult,
            response=assessment_result(),
        )
    )
    fake_llm._expectations = expectations
    session_id, revision = await _setup_intake_http(http_base)

    async with ws_connect(ws_url) as ws:
        for content in turn_messages:
            await ws.send(
                json.dumps(
                    {
                        "type": "send_message",
                        "session_id": session_id,
                        "client_message_id": str(uuid4()),
                        "request_id": str(uuid4()),
                        "expected_revision": revision,
                        "content": content,
                    }
                )
            )
            for _ in range(25):
                event = await _recv_json(ws)
                if event["type"] == "message_completed":
                    break
            async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
                revision = (await client.get("/api/v1/state")).json()["revision"]

        saw_operation = False
        saw_assessment_snapshot = False
        for _ in range(40):
            event = await _recv_json(ws)
            if event["type"] == "operation_changed":
                if (
                    event["operation"]["status"] == "pending"
                    and event["operation"]["kind"] == "assessment"
                ):
                    saw_operation = True
            if saw_operation and event["type"] == "snapshot_changed":
                if event["snapshot"]["stage"] == "assessment":
                    saw_assessment_snapshot = True
                    break
        assert saw_operation and saw_assessment_snapshot


async def test_duplicate_complete_submit_is_silent_on_websocket(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    fake_llm._expectations = list(intake_message_expectations("done once"))
    session_id, revision = await _setup_intake_http(http_base)
    client_message_id = uuid4()
    command = {
        "type": "send_message",
        "session_id": session_id,
        "client_message_id": str(client_message_id),
        "request_id": str(uuid4()),
        "expected_revision": revision,
        "content": "hello",
    }

    async with ws_connect(ws_url) as ws:
        await ws.send(json.dumps(command))
        for _ in range(25):
            event = await _recv_json(ws)
            if event["type"] == "message_completed":
                break
        else:
            pytest.fail("expected message_completed")

        completed_count = 0
        await ws.send(json.dumps({**command, "request_id": str(uuid4())}))
        for _ in range(10):
            try:
                event = await _recv_json(ws, timeout=1.0)
            except TimeoutError:
                break
            if event["type"] == "message_completed":
                completed_count += 1
        assert completed_count == 0
