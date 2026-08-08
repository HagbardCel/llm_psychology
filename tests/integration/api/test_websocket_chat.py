"""WebSocket integration tests against ephemeral Uvicorn."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

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
from tests.integration.application.application_fixtures import (
    completing_intake_patch,
    intake_message_expectations,
    post_session_expectations,
)
from tests.integration.application.scenarios import advance_to_ready
from tests.support.api import RuntimeProbe

pytestmark = pytest.mark.asyncio


async def _recv_json(ws, *, timeout: float = 15.0) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def receive_until_terminal(
    ws,
    *,
    max_events: int = 25,
) -> list[dict]:
    events: list[dict] = []
    for _ in range(max_events):
        event = await _recv_json(ws)
        events.append(event)
        if event["type"] in {"message_completed", "message_failed", "error"}:
            return events
    pytest.fail("terminal websocket event was not observed")


def _assert_one_shot_chat_shape(events: list[dict]) -> None:
    types = [event["type"] for event in events]
    assert types[-1] == "message_completed"
    assert "message_in_progress" not in types
    assert "snapshot_changed" not in types
    assert "operation_changed" not in types
    assert all(event_type == "token" for event_type in types[:-1])
    tokens = [event for event in events if event["type"] == "token"]
    completed = events[-1]
    for token in tokens:
        assert token["request_id"] == completed["request_id"]
        assert token["session_id"] == completed["session_id"]
        assert token["client_message_id"] == completed["client_message_id"]
        assert "sequence" not in token
        assert "turn_id" not in token
    joined = "".join(token["text"] for token in tokens)
    assert joined == completed["assistant_message"]["content"]


async def _receive_until(
    ws,
    predicate: Callable[[dict], bool],
    *,
    max_events: int = 15,
    timeout: float = 5.0,
) -> dict:
    for _ in range(max_events):
        event = await _recv_json(ws, timeout=timeout)
        if predicate(event):
            return event
    pytest.fail("matching websocket event was not observed")


async def _setup_intake_http(http_base: str) -> str:
    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        await client.put(
            "/api/v1/profile",
            json={
                "profile": {
                    "name": "Alex",
                    "primary_language": "English",
                    "date_of_birth": None,
                    "notes": None,
                },
            },
        )
        state = (await client.get("/api/v1/state")).json()
        return state["active_session"]["id"]


async def _send_message(ws, *, session_id: str, content: str, client_message_id=None):
    client_message_id = client_message_id or uuid4()
    request_id = uuid4()
    await ws.send(
        json.dumps(
            {
                "type": "send_message",
                "session_id": session_id,
                "client_message_id": str(client_message_id),
                "request_id": str(request_id),
                "content": content,
            }
        )
    )
    return client_message_id, request_id


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


async def test_invalid_command_closes_socket(
    uvicorn_api_urls,
) -> None:
    _http_base, ws_url = uvicorn_api_urls
    async with ws_connect(ws_url) as ws:
        await ws.send("not-json")
        err = await _recv_json(ws)
        assert err["type"] == "error"
        assert err["error"]["code"] == "validation_error"
        with pytest.raises(ConnectionClosed):
            await _recv_json(ws, timeout=1.0)


async def test_internal_error_sanitized_and_closes(
    uvicorn_api_urls,
    runtime_probe: RuntimeProbe,
    caplog: pytest.LogCaptureFixture,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    session_id = await _setup_intake_http(http_base)
    request_id = uuid4()
    client_message_id = uuid4()
    secret = "secret-runtime-detail"

    assert runtime_probe.runtime is not None

    async def boom(_command):
        raise RuntimeError(secret)
        if False:  # pragma: no cover
            yield

    runtime_probe.runtime.application.stream_message = boom  # type: ignore[method-assign]

    async with ws_connect(ws_url) as ws:
        with caplog.at_level(logging.ERROR, logger="jung.api.websocket"):
            await ws.send(
                json.dumps(
                    {
                        "type": "send_message",
                        "session_id": session_id,
                        "client_message_id": str(client_message_id),
                        "request_id": str(request_id),
                        "content": "hello",
                    }
                )
            )

            internal = await _receive_until(
                ws,
                lambda event: (
                    event["type"] == "error"
                    and event["error"]["code"] == "internal_error"
                    and event["request_id"] == str(request_id)
                ),
            )

        assert internal["session_id"] == session_id
        assert internal["client_message_id"] == str(client_message_id)
        assert internal["error"]["request_id"] == str(request_id)
        assert "turn_id" not in internal
        assert secret not in json.dumps(internal)
        assert secret not in caplog.text

        records = [
            record
            for record in caplog.records
            if record.message == "websocket_command_rejected"
            and getattr(record, "request_id", None) == str(request_id)
            and getattr(record, "error_code", None) == "internal_error"
        ]
        assert len(records) == 1
        assert getattr(records[0], "exception_type", None) == "RuntimeError"

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        health = await client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json() == {"status": "healthy"}


async def test_non_final_intake_streaming_order(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    fake_llm._expectations = list(intake_message_expectations("Hello there"))
    session_id = await _setup_intake_http(http_base)

    async with ws_connect(ws_url) as ws:
        await _send_message(ws, session_id=session_id, content="I feel anxious.")
        events = await receive_until_terminal(ws, max_events=25)
        _assert_one_shot_chat_shape(events)


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
    session_id = await _setup_intake_http(http_base)
    client_message_id = uuid4()

    async with ws_connect(ws_url) as ws:
        await _send_message(
            ws,
            session_id=session_id,
            content="trigger failure",
            client_message_id=client_message_id,
        )
        events = await receive_until_terminal(ws, max_events=25)
        assert events[-1]["type"] == "message_failed"
        failure = events[-1]
        assert failure["session_id"] == session_id
        assert failure["client_message_id"] == str(client_message_id)
        assert "turn_id" not in failure
        assert secret not in json.dumps(failure)
        assert "language model" in failure["error"]["message"].lower()

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        history = await client.get(f"/api/v1/sessions/{session_id}")
        roles = [message["role"] for message in history.json()["messages"]]
        assert roles == ["user"]


async def test_busy_rejects_concurrent_retry_while_generating(
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

    session_id = await _setup_intake_http(http_base)
    client_message_id = uuid4()

    async with ws_connect(ws_url) as first:
        await _send_message(
            ws=first,
            session_id=session_id,
            content="first",
            client_message_id=client_message_id,
        )
        await asyncio.wait_for(stream_started.wait(), timeout=5.0)

        async with ws_connect(ws_url) as second:
            await _send_message(
                ws=second,
                session_id=session_id,
                content="first",
                client_message_id=client_message_id,
            )
            busy_event = await _receive_until(
                second,
                lambda event: (
                    event["type"] == "error" and event["error"]["code"] == "busy"
                ),
            )
            assert busy_event is not None

        stream_gate.set()
        events = await receive_until_terminal(first)
        assert events[-1]["type"] == "message_completed"


async def test_disconnect_during_generation_leaves_unanswered_user(
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

    session_id = await _setup_intake_http(http_base)
    client_message_id = uuid4()

    async with ws_connect(ws_url) as ws:
        await _send_message(
            ws,
            session_id=session_id,
            content="hello",
            client_message_id=client_message_id,
        )
        await asyncio.wait_for(stream_started.wait(), timeout=5.0)

    stream_gate.set()
    await asyncio.sleep(0.2)
    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        history = await client.get(f"/api/v1/sessions/{session_id}")
        assert history.status_code == 200
        messages = history.json()["messages"]
        assert [message["role"] for message in messages] == ["user"]
        assert messages[0]["client_message_id"] == str(client_message_id)

    fake_llm._expectations = list(intake_message_expectations("completed after retry"))
    fake_llm.stream_text = FakeLLM.stream_text.__get__(fake_llm, FakeLLM)
    fake_llm.generate_structured = FakeLLM.generate_structured.__get__(
        fake_llm, FakeLLM
    )
    async with ws_connect(ws_url) as ws:
        await _send_message(
            ws,
            session_id=session_id,
            content="hello",
            client_message_id=client_message_id,
        )
        events = await receive_until_terminal(ws)
        assert events[-1]["type"] == "message_completed"
        assert events[-1]["assistant_message"]["content"] == "completed after retry"


async def test_final_intake_schedules_assessment_operation(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    from jung.phases.assessment.models import AssessmentResult
    from tests.integration.application.application_fixtures import assessment_result

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
    session_id = await _setup_intake_http(http_base)

    for content in turn_messages:
        async with ws_connect(ws_url) as ws:
            await _send_message(ws, session_id=session_id, content=content)
            events = await receive_until_terminal(ws)
            _assert_one_shot_chat_shape(events)

    async with httpx.AsyncClient(base_url=http_base, timeout=15.0) as client:
        for _ in range(50):
            state = (await client.get("/api/v1/state")).json()
            if state["stage"] == "assessment":
                assert state["operation"] is not None
                assert state["operation"]["kind"] == "assessment"
                return
            await asyncio.sleep(0.1)
    pytest.fail("assessment stage was not reached")


async def test_duplicate_complete_submit_is_idempotent_on_new_socket(
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, ws_url = uvicorn_api_urls
    fake_llm._expectations = list(intake_message_expectations("done once"))
    session_id = await _setup_intake_http(http_base)
    client_message_id = uuid4()

    async with ws_connect(ws_url) as ws:
        await _send_message(
            ws,
            session_id=session_id,
            content="hello",
            client_message_id=client_message_id,
        )
        events = await receive_until_terminal(ws)
        assert events[-1]["type"] == "message_completed"

    async with ws_connect(ws_url) as ws:
        await _send_message(
            ws,
            session_id=session_id,
            content="hello",
            client_message_id=client_message_id,
        )
        events = await receive_until_terminal(ws)
        assert events[-1]["type"] == "message_completed"
        assert events[-1]["assistant_message"]["content"] == "done once"

    fake_llm.assert_exhausted()


async def test_http_end_session_still_works_without_ws_broadcast(
    store: SQLiteStore,
    uvicorn_api_urls,
    fake_llm: FakeLLM,
) -> None:
    http_base, _ws_url = uvicorn_api_urls
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        session_id=therapy_id,
        now=ready.now,
    )
    fake_llm._expectations = list(post_session_expectations())

    async with httpx.AsyncClient(base_url=http_base, timeout=15.0) as client:
        state = (await client.get("/api/v1/state")).json()
        assert state["active_session"]["id"] == str(therapy_id)
        response = await client.post(f"/api/v1/sessions/{therapy_id}/end")
        assert response.status_code == 202
        assert response.json()["stage"] == "post_session"
        for _ in range(50):
            state = (await client.get("/api/v1/state")).json()
            if state.get("operation") and state["operation"]["kind"] == "post_session":
                return
            await asyncio.sleep(0.1)
    pytest.fail("post_session operation was not observed")
