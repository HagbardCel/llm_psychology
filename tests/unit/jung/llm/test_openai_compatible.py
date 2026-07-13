"""Tests for OpenAI-compatible gateway with mocked transport."""

from __future__ import annotations

import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from jung.llm.errors import (
    InvalidLLMOutput,
    LLMProtocolError,
    LLMTimeout,
    LLMUnavailable,
)
from jung.llm.gateway import (
    AdapterConfig,
    ChatMessage,
    ChatRole,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
)
from jung.llm.openai_compatible import OpenAICompatibleLLM, ProviderAttemptEvent


class _Answer(BaseModel):
    value: str


def _policy(*, mode: StructuredOutputMode = StructuredOutputMode.JSON_OBJECT) -> ModelPolicy:
    return ModelPolicy(
        task=LLMTask.ASSESSMENT,
        model="test-model",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=mode,
    )


def _client(
    handler: httpx.MockTransport,
    *,
    config: AdapterConfig | None = None,
    on_provider_attempt: object | None = None,
) -> OpenAICompatibleLLM:
    adapter_config = config or AdapterConfig(
        base_url="http://testserver/v1",
        api_key="test",
    )
    kwargs: dict[str, object] = {}
    if on_provider_attempt is not None:
        kwargs["on_provider_attempt"] = on_provider_attempt
    return OpenAICompatibleLLM(
        adapter_config,
        client=AsyncOpenAI(
            base_url=adapter_config.base_url,
            api_key=adapter_config.api_key,
            http_client=httpx.AsyncClient(transport=handler),
            max_retries=0,
        ),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_stream_text_yields_non_empty_chunks() -> None:
    chunk = json.dumps(
        {
            "id": "1",
            "object": "chat.completion.chunk",
            "choices": [{"delta": {"content": "hi"}, "index": 0}],
        }
    )
    sse_body = f"data: {chunk}\n\ndata: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=sse_body,
            headers={"content-type": "text/event-stream"},
        )

    gateway = _client(httpx.MockTransport(handler))
    chunks = [
        chunk
        async for chunk in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hello")],
            _policy(mode=StructuredOutputMode.PROMPT),
        )
    ]
    assert chunks == ["hi"]


@pytest.mark.asyncio
async def test_generate_structured_validates_json_object_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"value":"ok"}'},
                        "index": 0,
                    }
                ],
            },
        )

    gateway = _client(httpx.MockTransport(handler))
    result = await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(),
    )
    assert result.value == "ok"


@pytest.mark.asyncio
async def test_generate_structured_retries_once_then_raises() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"value":1}'},
                        "index": 0,
                    }
                ],
            },
        )

    gateway = _client(httpx.MockTransport(handler))
    with pytest.raises(InvalidLLMOutput):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_connection_error_maps_to_llm_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    gateway = _client(httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable):
        async for _ in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hello")],
            _policy(mode=StructuredOutputMode.PROMPT),
        ):
            pass


@pytest.mark.asyncio
async def test_request_includes_max_completion_tokens_when_set() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"value":"ok"}'},
                        "index": 0,
                    }
                ],
            },
        )

    gateway = _client(httpx.MockTransport(handler))
    policy = ModelPolicy(
        task=LLMTask.ASSESSMENT,
        model="test-model",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.JSON_OBJECT,
        max_completion_tokens=128,
    )
    await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        policy,
    )
    body = captured["body"]
    assert isinstance(body, dict)
    assert body.get("max_completion_tokens") == 128


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (408, LLMTimeout),
        (429, LLMUnavailable),
        (503, LLMUnavailable),
        (400, LLMProtocolError),
    ],
)
async def test_http_status_maps_to_expected_error(
    status: int,
    expected: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "boom"}})

    gateway = _client(httpx.MockTransport(handler))
    with pytest.raises(expected):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )


@pytest.mark.asyncio
async def test_prompt_mode_correction_preserves_schema_instruction() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode()))
        content = '{"value":"ok"}' if len(bodies) == 2 else '{"value":1}'
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "index": 0,
                    }
                ],
            },
        )

    gateway = _client(httpx.MockTransport(handler))
    result = await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(mode=StructuredOutputMode.PROMPT),
    )
    assert result.value == "ok"
    assert len(bodies) == 2
    second_messages = bodies[1]["messages"]
    combined = json.dumps(second_messages)
    assert "Respond with JSON only that matches this schema" in combined
    assert "was invalid" in combined


@pytest.mark.asyncio
async def test_validator_runtime_error_propagates_without_correction() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"value":"ok"}'},
                        "index": 0,
                    }
                ],
            },
        )

    def broken_validator(result: _Answer) -> _Answer:
        raise RuntimeError("programming defect")

    gateway = _client(httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="programming defect"):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
            validate_result=broken_validator,
        )
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_semantic_validator_failure_triggers_single_correction() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        content = '{"value":"ok"}' if calls["count"] == 2 else '{"value":"bad"}'
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "index": 0,
                    }
                ],
            },
        )

    def validator(result: _Answer) -> _Answer:
        if result.value != "ok":
            raise ValueError("semantic mismatch")
        return result

    gateway = _client(httpx.MockTransport(handler))
    result = await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(),
        validate_result=validator,
    )
    assert result.value == "ok"
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_stream_cancellation_propagates() -> None:
    import asyncio

    def handler(request: httpx.Request) -> httpx.Response:
        chunk = json.dumps(
            {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "hi"}, "index": 0}],
            }
        )
        sse_body = f"data: {chunk}\n\ndata: [DONE]\n\n"
        return httpx.Response(
            200,
            content=sse_body,
            headers={"content-type": "text/event-stream"},
        )

    gateway = _client(httpx.MockTransport(handler))

    async def consume() -> None:
        async for _ in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hello")],
            _policy(mode=StructuredOutputMode.PROMPT),
        ):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await consume()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_type"),
    [
        (StructuredOutputMode.JSON_SCHEMA, "json_schema"),
        (StructuredOutputMode.JSON_OBJECT, "json_object"),
        (StructuredOutputMode.PROMPT, None),
    ],
)
async def test_response_format_for_structured_mode(
    mode: StructuredOutputMode,
    expected_type: str | None,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"value":"ok"}'},
                        "index": 0,
                    }
                ],
            },
        )

    gateway = _client(httpx.MockTransport(handler))
    await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(mode=mode),
    )
    body = captured["body"]
    assert isinstance(body, dict)
    response_format = body.get("response_format")
    if expected_type is None:
        assert response_format is None
    else:
        assert isinstance(response_format, dict)
        assert response_format.get("type") == expected_type


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "expected_extra"),
    [
        (
            AdapterConfig(
                base_url="http://testserver/v1",
                api_key="test",
                extra_body={"thinking": True, "shared": "global"},
                task_extra_body={
                    LLMTask.ASSESSMENT: {
                        "shared": "task",
                        "reasoning_effort": "low",
                    }
                },
            ),
            {"thinking": True, "shared": "task", "reasoning_effort": "low"},
        ),
    ],
)
async def test_extra_body_merge_applies_task_overrides(
    config: AdapterConfig,
    expected_extra: dict[str, object],
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"value":"ok"}'},
                        "index": 0,
                    }
                ],
            },
        )

    gateway = _client(httpx.MockTransport(handler), config=config)
    await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(),
    )
    body = captured["body"]
    assert isinstance(body, dict)
    for key, value in expected_extra.items():
        assert body.get(key) == value
    assert body.get("model") == "test-model"
    assert body.get("messages")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [
        AdapterConfig(
            base_url="http://testserver/v1",
            api_key="test",
            extra_body={"model": "override"},
        ),
        AdapterConfig(
            base_url="http://testserver/v1",
            api_key="test",
            task_extra_body={LLMTask.ASSESSMENT: {"response_format": {"type": "json_object"}}},
        ),
        AdapterConfig(
            base_url="http://testserver/v1",
            api_key="test",
            extra_body={"stream": True},
        ),
        AdapterConfig(
            base_url="http://testserver/v1",
            api_key="test",
            extra_body={"temperature": 0.2},
        ),
    ],
)
async def test_extra_body_rejects_forbidden_core_fields(config: AdapterConfig) -> None:
    gateway = _client(httpx.MockTransport(lambda request: httpx.Response(500)), config=config)
    with pytest.raises(ValueError, match="extra_body cannot override adapter-owned fields"):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )


@pytest.mark.asyncio
async def test_provider_attempt_event_emitted_on_initial_success() -> None:
    events: list[ProviderAttemptEvent] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"value":"ok"}'},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    gateway = _client(
        httpx.MockTransport(handler),
        on_provider_attempt=events.append,
    )
    await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(),
    )
    assert len(events) == 1
    event = events[0]
    assert event.attempt == "initial"
    assert event.status == "success"
    assert event.response_chars == len('{"value":"ok"}')
    assert event.finish_reason == "stop"
    assert event.prompt_tokens == 10
    assert event.completion_tokens == 5


@pytest.mark.asyncio
async def test_correction_trigger_classified_for_semantic_and_schema_failures() -> None:
    events: list[ProviderAttemptEvent] = []
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            content = '{"value":"bad"}'
        else:
            content = '{"value":"ok"}'
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "index": 0,
                    }
                ],
            },
        )

    def validator(result: _Answer) -> _Answer:
        if result.value != "ok":
            raise ValueError("semantic mismatch")
        return result

    gateway = _client(
        httpx.MockTransport(handler),
        on_provider_attempt=events.append,
    )
    await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(),
        validate_result=validator,
    )
    assert len(events) == 2
    assert events[1].attempt == "correction"
    assert events[1].correction_trigger == "semantic_validation"


@pytest.mark.asyncio
async def test_unclassified_invalid_output_uses_schema_correction_trigger() -> None:
    events: list[ProviderAttemptEvent] = []
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        content = '{"value":"ok"}' if calls["count"] == 2 else ""
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "index": 0,
                    }
                ],
            },
        )

    gateway = _client(
        httpx.MockTransport(handler),
        on_provider_attempt=events.append,
    )
    await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(),
    )
    assert len(events) == 2
    assert events[1].correction_trigger == "syntactic_or_schema_validation"


@pytest.mark.asyncio
async def test_raising_observer_does_not_corrupt_provider_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"value":"ok"}'},
                        "index": 0,
                    }
                ],
            },
        )

    def broken_observer(_event: ProviderAttemptEvent) -> None:
        raise RuntimeError("observer bug")

    gateway = _client(
        httpx.MockTransport(handler),
        on_provider_attempt=broken_observer,
    )
    result = await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(),
    )
    assert result.value == "ok"


class _UnexpectedProviderBug(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_unexpected_provider_error_propagates_unchanged_structured() -> None:
    gateway = _client(httpx.MockTransport(lambda request: httpx.Response(500)))

    async def boom(**_kwargs: object) -> object:
        raise _UnexpectedProviderBug("sdk defect")

    gateway._client.chat.completions.create = boom  # type: ignore[method-assign]

    with pytest.raises(_UnexpectedProviderBug, match="sdk defect"):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )


@pytest.mark.asyncio
async def test_unexpected_provider_error_propagates_unchanged_stream() -> None:
    gateway = _client(httpx.MockTransport(lambda request: httpx.Response(500)))

    async def boom(**_kwargs: object) -> object:
        raise _UnexpectedProviderBug("sdk defect")

    gateway._client.chat.completions.create = boom  # type: ignore[method-assign]

    with pytest.raises(_UnexpectedProviderBug, match="sdk defect"):
        async for _ in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hello")],
            _policy(mode=StructuredOutputMode.PROMPT),
        ):
            pass


@pytest.mark.asyncio
async def test_response_chars_measures_raw_content_before_fence_strip() -> None:
    events: list[ProviderAttemptEvent] = []
    fenced = '```json\n{"value":"ok"}\n```'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": fenced},
                        "index": 0,
                    }
                ],
            },
        )

    gateway = _client(
        httpx.MockTransport(handler),
        on_provider_attempt=events.append,
    )
    await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(),
    )
    assert len(events) == 1
    assert events[0].response_chars == len(fenced)
    assert events[0].response_chars != len('{"value":"ok"}')


@pytest.mark.asyncio
async def test_validator_invalid_llm_output_records_semantic_correction_trigger() -> None:
    events: list[ProviderAttemptEvent] = []
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        content = '{"value":"ok"}' if calls["count"] == 2 else '{"value":"bad"}'
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "index": 0,
                    }
                ],
            },
        )

    def validator(result: _Answer) -> _Answer:
        if result.value != "ok":
            raise InvalidLLMOutput("semantic mismatch")
        return result

    gateway = _client(
        httpx.MockTransport(handler),
        on_provider_attempt=events.append,
    )
    result = await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(),
        validate_result=validator,
    )
    assert result.value == "ok"
    assert len(events) == 2
    assert events[1].correction_trigger == "semantic_validation"
