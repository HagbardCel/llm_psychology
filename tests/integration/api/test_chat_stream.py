"""HTTP NDJSON chat stream integration tests against ephemeral Uvicorn."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

import httpx
import pytest

from jung.api.contracts import (
    ErrorEvent,
    MessageCompletedEvent,
    MessageFailedEvent,
    ServerEvent,
    TokenEvent,
)
from jung.client.api_client import ServerEventAdapter
from jung.domain.errors import InvariantViolation
from jung.llm.errors import LLMUnavailable
from jung.llm.fake import (
    FailureExpectation,
    FakeLLM,
    StreamExpectation,
    StructuredExpectation,
)
from jung.llm.gateway import LLMTask
from jung.phases.intake.models import IntakeRecordPatch
from tests.integration.application.application_fixtures import (
    intake_message_expectations,
)
from tests.support.api import HoldingFakeLLM, RuntimeProbe

pytestmark = pytest.mark.asyncio


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


def _chat_headers(request_id: UUID) -> dict[str, str]:
    return {
        "X-Request-ID": str(request_id),
        "Accept": "application/x-ndjson",
    }


def _chat_body(
    *,
    session_id: str,
    content: str,
    client_message_id: UUID,
) -> dict[str, str]:
    return {
        "session_id": session_id,
        "client_message_id": str(client_message_id),
        "content": content,
    }


async def _read_events(
    response: httpx.Response,
    *,
    max_events: int = 25,
) -> list[ServerEvent]:
    events: list[ServerEvent] = []
    async for line in response.aiter_lines():
        if not line:
            continue
        event = ServerEventAdapter.validate_json(line)
        events.append(event)
        if isinstance(event, (MessageCompletedEvent, MessageFailedEvent, ErrorEvent)):
            return events
        if len(events) >= max_events:
            pytest.fail("terminal chat event was not observed")
    return events


def _assert_normal_completion_shape(events: list[ServerEvent]) -> None:
    assert events
    assert isinstance(events[-1], MessageCompletedEvent)
    assert all(isinstance(event, TokenEvent) for event in events[:-1])
    completed = events[-1]
    for token in events[:-1]:
        assert isinstance(token, TokenEvent)
        assert token.request_id == completed.request_id
        assert token.session_id == completed.session_id
        assert token.client_message_id == completed.client_message_id
    joined = "".join(
        token.text for token in events[:-1] if isinstance(token, TokenEvent)
    )
    assert joined == completed.assistant_message.content


async def test_successful_stream_tokens_then_completion(
    uvicorn_api_url,
    fake_llm: FakeLLM,
) -> None:
    http_base = uvicorn_api_url
    fake_llm._expectations = list(intake_message_expectations("hello world"))
    session_id = await _setup_intake_http(http_base)
    request_id = uuid4()
    client_message_id = uuid4()

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(request_id),
            json=_chat_body(
                session_id=session_id,
                content="hi",
                client_message_id=client_message_id,
            ),
        ) as response:
            assert response.status_code == 200
            assert response.headers["X-Request-ID"] == str(request_id)
            assert "application/x-ndjson" in response.headers["content-type"]
            events = await _read_events(response)
            _assert_normal_completion_shape(events)
            for event in events:
                assert event.request_id == request_id


async def test_request_id_consistency_across_header_and_events(
    uvicorn_api_url,
    fake_llm: FakeLLM,
) -> None:
    http_base = uvicorn_api_url
    fake_llm._expectations = list(intake_message_expectations("ok"))
    session_id = await _setup_intake_http(http_base)
    request_id = uuid4()
    client_message_id = uuid4()

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(request_id),
            json=_chat_body(
                session_id=session_id,
                content="hi",
                client_message_id=client_message_id,
            ),
        ) as response:
            assert response.headers["X-Request-ID"] == str(request_id)
            events = await _read_events(response)
            assert all(event.request_id == request_id for event in events)


async def test_accepted_llm_failure_leaves_unanswered_user(
    uvicorn_api_url,
    fake_llm: FakeLLM,
) -> None:
    http_base = uvicorn_api_url
    secret = "SECRET_PROVIDER_DETAIL"
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
    request_id = uuid4()
    client_message_id = uuid4()

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(request_id),
            json=_chat_body(
                session_id=session_id,
                content="trigger failure",
                client_message_id=client_message_id,
            ),
        ) as response:
            events = await _read_events(response)
            assert isinstance(events[-1], MessageFailedEvent)
            payload = events[-1].model_dump_json()
            assert secret not in payload

        history = await client.get(f"/api/v1/sessions/{session_id}")
        roles = [message["role"] for message in history.json()["messages"]]
        assert roles == ["user"]


async def test_command_rejection_is_stream_error_event(
    uvicorn_api_url,
) -> None:
    http_base = uvicorn_api_url
    await _setup_intake_http(http_base)
    request_id = uuid4()
    # Use a nonexistent session — command rejection surfaces as an in-stream ErrorEvent.
    missing_session = uuid4()

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(request_id),
            json=_chat_body(
                session_id=str(missing_session),
                content="hello",
                client_message_id=uuid4(),
            ),
        ) as response:
            assert response.status_code == 200
            events = await _read_events(response)
            assert isinstance(events[-1], ErrorEvent)
            assert events[-1].error.code in {"invalid_command", "not_found", "busy"}
            assert events[-1].request_id == request_id


async def test_malformed_body_is_ordinary_http_422(uvicorn_api_url) -> None:
    http_base = uvicorn_api_url
    request_id = uuid4()
    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        response = await client.post(
            "/api/v1/chat",
            headers=_chat_headers(request_id),
            json={"session_id": "not-a-uuid"},
        )
        assert response.status_code == 422
        assert "application/json" in response.headers["content-type"]
        body = response.json()
        assert body["code"] == "validation_error"
        assert body["request_id"] == str(request_id)


async def test_duplicate_completed_id_is_idempotent(
    uvicorn_api_url,
    fake_llm: FakeLLM,
) -> None:
    http_base = uvicorn_api_url
    fake_llm._expectations = list(intake_message_expectations("done once"))
    session_id = await _setup_intake_http(http_base)
    client_message_id = uuid4()

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(uuid4()),
            json=_chat_body(
                session_id=session_id,
                content="hello",
                client_message_id=client_message_id,
            ),
        ) as response:
            events = await _read_events(response)
            assert isinstance(events[-1], MessageCompletedEvent)

        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(uuid4()),
            json=_chat_body(
                session_id=session_id,
                content="hello",
                client_message_id=client_message_id,
            ),
        ) as response:
            events = await _read_events(response)
            assert isinstance(events[-1], MessageCompletedEvent)
            assert events[-1].assistant_message.content == "done once"

    fake_llm.assert_exhausted()


async def test_duplicate_id_different_content_is_invalid_command(
    uvicorn_api_url,
    fake_llm: FakeLLM,
) -> None:
    http_base = uvicorn_api_url
    fake_llm._expectations = list(intake_message_expectations("first"))
    session_id = await _setup_intake_http(http_base)
    client_message_id = uuid4()

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(uuid4()),
            json=_chat_body(
                session_id=session_id,
                content="hello",
                client_message_id=client_message_id,
            ),
        ) as response:
            events = await _read_events(response)
            assert isinstance(events[-1], MessageCompletedEvent)

        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(uuid4()),
            json=_chat_body(
                session_id=session_id,
                content="different content",
                client_message_id=client_message_id,
            ),
        ) as response:
            events = await _read_events(response)
            assert isinstance(events[-1], ErrorEvent)
            assert events[-1].error.code == "invalid_command"


async def test_unicode_and_newlines_in_tokens(
    uvicorn_api_url,
    fake_llm: FakeLLM,
) -> None:
    http_base = uvicorn_api_url
    text = "line1\nline2 — café 你好"
    fake_llm._expectations = list(intake_message_expectations(text))
    session_id = await _setup_intake_http(http_base)

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(uuid4()),
            json=_chat_body(
                session_id=session_id,
                content="hi",
                client_message_id=uuid4(),
            ),
        ) as response:
            events = await _read_events(response)
            _assert_normal_completion_shape(events)
            assert isinstance(events[-1], MessageCompletedEvent)
            assert events[-1].assistant_message.content == text


async def test_incremental_delivery_before_llm_release(
    uvicorn_api_url,
    fake_llm: FakeLLM,
) -> None:
    http_base = uvicorn_api_url
    holding = HoldingFakeLLM(list(intake_message_expectations("after release")))
    fake_llm._expectations = holding._expectations
    fake_llm.generate_structured = holding.generate_structured  # type: ignore[method-assign]
    fake_llm.stream_text = holding.stream_text  # type: ignore[method-assign]

    session_id = await _setup_intake_http(http_base)
    request_id = uuid4()
    client_message_id = uuid4()

    async with httpx.AsyncClient(base_url=http_base, timeout=None) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(request_id),
            json=_chat_body(
                session_id=session_id,
                content="hello",
                client_message_id=client_message_id,
            ),
            timeout=httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0),
        ) as response:
            assert response.status_code == 200
            lines = response.aiter_lines()
            first_line = await anext(lines)
            while not first_line:
                first_line = await anext(lines)
            first = ServerEventAdapter.validate_json(first_line)
            assert isinstance(first, TokenEvent)
            await asyncio.wait_for(holding.first_chunk_emitted.wait(), timeout=5.0)
            assert not holding._release_event.is_set()

            holding.release()
            remaining: list[ServerEvent] = [first]
            async for line in lines:
                if not line:
                    continue
                event = ServerEventAdapter.validate_json(line)
                remaining.append(event)
                if isinstance(
                    event, (MessageCompletedEvent, MessageFailedEvent, ErrorEvent)
                ):
                    break
            assert isinstance(remaining[-1], MessageCompletedEvent)


async def test_disconnect_cancels_held_generation_and_is_reconcilable(
    uvicorn_api_url,
    fake_llm: FakeLLM,
) -> None:
    http_base = uvicorn_api_url
    holding = HoldingFakeLLM(list(intake_message_expectations("partial then hold")))
    # Ensure first chunk is observable then hold forever until cancelled.
    holding._expectations = [
        holding._expectations[0],
        StreamExpectation(task=LLMTask.INTAKE_RESPONSE, chunks=("partial", "more")),
    ]
    fake_llm._expectations = holding._expectations
    fake_llm.generate_structured = holding.generate_structured  # type: ignore[method-assign]
    fake_llm.stream_text = holding.stream_text  # type: ignore[method-assign]

    session_id = await _setup_intake_http(http_base)
    client_message_id = uuid4()

    async with httpx.AsyncClient(base_url=http_base, timeout=None) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(uuid4()),
            json=_chat_body(
                session_id=session_id,
                content="hello",
                client_message_id=client_message_id,
            ),
            timeout=httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0),
        ) as response:
            lines = response.aiter_lines()
            first_line = await anext(lines)
            while not first_line:
                first_line = await anext(lines)
            first = ServerEventAdapter.validate_json(first_line)
            assert isinstance(first, TokenEvent)
            await asyncio.wait_for(holding.first_chunk_emitted.wait(), timeout=5.0)
            # Exit stream context without reading further → disconnect.

    await asyncio.wait_for(holding.stream_closed.wait(), timeout=5.0)

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        history = await client.get(f"/api/v1/sessions/{session_id}")
        messages = history.json()["messages"]
        assert [message["role"] for message in messages] == ["user"]
        assert messages[0]["client_message_id"] == str(client_message_id)

    fake_llm._expectations = list(intake_message_expectations("completed after retry"))
    fake_llm.stream_text = FakeLLM.stream_text.__get__(fake_llm, FakeLLM)
    fake_llm.generate_structured = FakeLLM.generate_structured.__get__(
        fake_llm, FakeLLM
    )

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(uuid4()),
            json=_chat_body(
                session_id=session_id,
                content="hello",
                client_message_id=client_message_id,
            ),
        ) as response:
            events = await _read_events(response)
            assert isinstance(events[-1], MessageCompletedEvent)
            assert events[-1].assistant_message.content == "completed after retry"


async def test_internal_domain_error_is_logged_and_sanitized(
    uvicorn_api_url,
    runtime_probe: RuntimeProbe,
    caplog: pytest.LogCaptureFixture,
) -> None:
    http_base = uvicorn_api_url
    session_id = await _setup_intake_http(http_base)
    request_id = uuid4()
    client_message_id = uuid4()
    secret = "secret-runtime-detail"

    assert runtime_probe.runtime is not None
    application = runtime_probe.runtime.application

    async def fail_stream(command):
        if False:
            yield
        raise InvariantViolation(secret)

    application.stream_message = fail_stream  # type: ignore[method-assign]

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        with caplog.at_level(logging.ERROR, logger="jung.api.routes"):
            async with client.stream(
                "POST",
                "/api/v1/chat",
                headers=_chat_headers(request_id),
                json=_chat_body(
                    session_id=session_id,
                    content="hi",
                    client_message_id=client_message_id,
                ),
            ) as response:
                assert response.status_code == 200
                events = await _read_events(response)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ErrorEvent)
    assert event.error.code == "internal_error"
    assert event.request_id == request_id
    assert event.session_id == UUID(session_id)
    assert event.client_message_id == client_message_id
    assert event.error.request_id == request_id
    assert secret not in event.model_dump_json()
    assert secret not in caplog.text

    records = [
        record
        for record in caplog.records
        if record.name == "jung.api.routes"
        and record.levelno == logging.ERROR
        and record.getMessage() == "chat stream failed"
        and getattr(record, "request_id", None) == str(request_id)
    ]
    assert len(records) == 1
    assert getattr(records[0], "exception_type", None) == "InvariantViolation"


async def test_normal_completion_terminal_is_final_then_eof(
    uvicorn_api_url,
    fake_llm: FakeLLM,
) -> None:
    http_base = uvicorn_api_url
    fake_llm._expectations = list(intake_message_expectations("eof complete"))
    session_id = await _setup_intake_http(http_base)
    request_id = uuid4()
    client_message_id = uuid4()

    async with httpx.AsyncClient(base_url=http_base, timeout=10.0) as client:
        async with client.stream(
            "POST",
            "/api/v1/chat",
            headers=_chat_headers(request_id),
            json=_chat_body(
                session_id=session_id,
                content="hi",
                client_message_id=client_message_id,
            ),
        ) as response:
            assert response.status_code == 200
            events: list[ServerEvent] = []
            lines = response.aiter_lines()

            async with asyncio.timeout(5.0):
                async for line in lines:
                    if line:
                        events.append(ServerEventAdapter.validate_json(line))

    terminals = [
        event
        for event in events
        if isinstance(event, (MessageCompletedEvent, MessageFailedEvent, ErrorEvent))
    ]
    assert len(terminals) == 1
    assert events[-1] is terminals[0]
    _assert_normal_completion_shape(events)
