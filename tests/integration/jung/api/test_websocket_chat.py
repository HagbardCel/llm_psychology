"""WebSocket integration tests against ephemeral Uvicorn."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import InvalidHandshake

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


async def receive_until_completion_snapshot(
    ws,
    *,
    max_events: int = 25,
) -> list[dict]:
    events: list[dict] = []
    saw_completion = False

    for _ in range(max_events):
        event = await _recv_json(ws)
        events.append(event)

        if event["type"] == "message_completed":
            saw_completion = True
        elif saw_completion and event["type"] == "snapshot_changed":
            return events

    pytest.fail("message_completed followed by snapshot_changed was not observed")


def _assert_normal_chat_event_shape(events: list[dict]) -> None:
    types = [event["type"] for event in events]
    assert len(types) >= 5
    assert types[:2] == ["message_in_progress", "snapshot_changed"]
    assert types[-2:] == ["message_completed", "snapshot_changed"]
    assert all(event_type == "token" for event_type in types[2:-2])


async def _recv_matching_progress(
    ws,
    *,
    session_id: str,
    client_message_id: UUID,
    timeout: float = 5.0,
) -> dict:
    try:
        async with asyncio.timeout(timeout):
            for _ in range(15):
                event = await _recv_json(ws, timeout=timeout)
                if (
                    event["type"] == "message_in_progress"
                    and event["session_id"] == session_id
                    and event["turn"]["client_message_id"] == str(client_message_id)
                ):
                    return event
    except TimeoutError:
        pytest.fail(
            "timed out waiting for matching message_in_progress "
            f"for client_message_id={client_message_id}"
        )

    pytest.fail(
        "matching message_in_progress was not observed within the event limit"
    )


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


async def test_websocket_accepts_configured_browser_origin(uvicorn_api_urls) -> None:
    _http_base, ws_url = uvicorn_api_urls
    async with ws_connect(ws_url, origin="http://frontend.test"):
        return


async def test_websocket_rejects_disallowed_browser_origin(uvicorn_api_urls) -> None:
    _http_base, ws_url = uvicorn_api_urls
    with pytest.raises(InvalidHandshake):
        async with ws_connect(ws_url, origin="http://evil.test"):
            pytest.fail("disallowed Origin was accepted")


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

        events = await receive_until_completion_snapshot(ws, max_events=25)
        types = [event["type"] for event in events]
        tokens = [event for event in events if event["type"] == "token"]
        completed = next(event for event in events if event["type"] == "message_completed")

        assert len(types) >= 5
        assert types[:2] == ["message_in_progress", "snapshot_changed"]
        assert types[-2:] == ["message_completed", "snapshot_changed"]
        assert all(event_type == "token" for event_type in types[2:-2])
        assert tokens
        sequences = [token["sequence"] for token in tokens]
        assert sequences == list(range(1, len(sequences) + 1))
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
                    "content": "trigger failure",
                }
            )
        )
        events: list[dict] = []
        error_event = None
        for _ in range(25):
            event = await _recv_json(ws)
            events.append(event)
            if event["type"] == "error":
                error_event = event
                break

        assert error_event is not None
        types = [event["type"] for event in events]
        assert types[:2] == ["message_in_progress", "snapshot_changed"]
        assert all(event_type == "token" for event_type in types[2:-1])
        assert types[-1] == "error"

        progress = events[0]
        acceptance_snapshot = events[1]["snapshot"]

        assert error_event["session_id"] == session_id
        assert error_event["turn_id"] == progress["turn"]["id"]
        assert error_event["client_message_id"] == str(client_message_id)

        assert secret not in json.dumps(error_event)
        assert "language model" in error_event["error"]["message"].lower()

        trailing = await _recv_json(ws)
        assert trailing["type"] == "snapshot_changed"
        assert trailing["snapshot"]["revision"] > acceptance_snapshot["revision"]
        assert trailing["snapshot"]["active_chat_turn"] is None
        assert trailing["snapshot"]["stage"] == "intake"


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

        operation_events = [
            event
            for event in events
            if event.get("type") == "operation_changed"
            and event.get("operation", {}).get("kind") == "post_session"
            and event.get("operation", {}).get("status") == "pending"
            and event.get("snapshot", {}).get("stage") == "post_session"
        ]
        assert len(operation_events) >= 1
        event = operation_events[-1]
        assert event["type"] == "operation_changed"
        assert event["operation"]["kind"] == "post_session"
        assert event["operation"]["status"] == "pending"
        assert event["snapshot"]["stage"] == "post_session"


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
        for content in turn_messages[:-1]:
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
            turn_events = await receive_until_completion_snapshot(ws, max_events=25)
            _assert_normal_chat_event_shape(turn_events)
            async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
                revision = (await client.get("/api/v1/state")).json()["revision"]

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "session_id": session_id,
                    "client_message_id": str(uuid4()),
                    "request_id": str(uuid4()),
                    "expected_revision": revision,
                    "content": turn_messages[-1],
                }
            )
        )

        final_events: list[dict] = []
        saw_assessment_snapshot = False
        for _ in range(40):
            event = await _recv_json(ws)
            final_events.append(event)
            if event["type"] == "snapshot_changed" and event["snapshot"]["stage"] == "assessment":
                saw_assessment_snapshot = True
                break

        types = [event["type"] for event in final_events]

        assert len(types) >= 6
        assert types[:2] == ["message_in_progress", "snapshot_changed"]
        assert types[-3:] == ["message_completed", "operation_changed", "snapshot_changed"]
        assert types[2:-3]
        assert all(event_type == "token" for event_type in types[2:-3])

        operation_event = final_events[-2]
        trailing = final_events[-1]

        assert operation_event["operation"]["kind"] == "assessment"
        assert operation_event["operation"]["status"] == "pending"
        assert operation_event["snapshot"]["stage"] == "assessment"
        assert trailing["snapshot"]["stage"] == "assessment"
        assert trailing["snapshot"]["revision"] == operation_event["snapshot"]["revision"]
        assert saw_assessment_snapshot


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


async def test_revision_conflict_includes_snapshot_and_retransmit_succeeds(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    fake_llm._expectations = list(
        intake_message_expectations("corrected request response")
    )
    session_id, revision = await _setup_intake_http(http_base)

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        authoritative_revision = revision
        await client.put(
            "/api/v1/profile",
            json={
                "expected_revision": authoritative_revision,
                "profile": {
                    "name": "Alex",
                    "primary_language": "English",
                    "date_of_birth": None,
                    "notes": "revision bump",
                },
            },
        )
        state = (await client.get("/api/v1/state")).json()
        authoritative_revision = state["revision"]
        assert authoritative_revision > revision

    stale_request_id = uuid4()
    client_message_id = uuid4()
    content = "stale revision attempt"

    async with ws_connect(ws_url) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "session_id": session_id,
                    "client_message_id": str(client_message_id),
                    "request_id": str(stale_request_id),
                    "expected_revision": revision,
                    "content": content,
                }
            )
        )
        error_event = await _recv_json(ws)
        assert error_event["request_id"] == str(stale_request_id)
        assert error_event["error"]["request_id"] == str(stale_request_id)
        assert error_event["session_id"] == session_id
        assert error_event["client_message_id"] == str(client_message_id)
        assert error_event["turn_id"] is None
        assert error_event["error"]["code"] == "state_conflict"
        assert (
            error_event["error"]["current_snapshot"]["revision"]
            == authoritative_revision
        )

        async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
            history = await client.get(f"/api/v1/sessions/{session_id}")
            assert not any(
                message["client_message_id"] == str(client_message_id)
                for message in history.json()["messages"]
            )

        corrected_request_id = uuid4()
        assert corrected_request_id != stale_request_id

        await ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "session_id": session_id,
                    "client_message_id": str(client_message_id),
                    "request_id": str(corrected_request_id),
                    "expected_revision": authoritative_revision,
                    "content": content,
                }
            )
        )
        progress = await _recv_matching_progress(
            ws,
            session_id=session_id,
            client_message_id=client_message_id,
        )
        assert progress["session_id"] == session_id
        assert progress["turn"]["client_message_id"] == str(client_message_id)
        assert progress["turn"]["session_id"] == session_id

        token_event = None
        for _ in range(15):
            event = await _recv_json(ws)
            if event["type"] == "token":
                token_event = event
                break
        assert token_event is not None
        assert token_event["request_id"] == str(corrected_request_id)
