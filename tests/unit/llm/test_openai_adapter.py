"""Tests for OpenAI-compatible gateway with mocked transport."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.asyncio
from openai import APIStatusError, AsyncOpenAI
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


def _policy(
    *, mode: StructuredOutputMode = StructuredOutputMode.JSON_OBJECT
) -> ModelPolicy:
    return ModelPolicy(
        task=LLMTask.ASSESSMENT,
        model="test-model",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=mode,
    )


def _client(
    transport: httpx.AsyncBaseTransport,
    *,
    config: AdapterConfig | None = None,
    on_provider_attempt: object | None = None,
    recorder: object | None = None,
) -> OpenAICompatibleLLM:
    adapter_config = config or AdapterConfig(
        base_url="http://testserver/v1",
        api_key="test",
    )
    kwargs: dict[str, object] = {}
    if on_provider_attempt is not None:
        kwargs["on_provider_attempt"] = on_provider_attempt
    if recorder is not None:
        kwargs["recorder"] = recorder
    return OpenAICompatibleLLM(
        adapter_config,
        client=AsyncOpenAI(
            base_url=adapter_config.base_url,
            api_key=adapter_config.api_key,
            http_client=httpx.AsyncClient(transport=transport),
            max_retries=0,
        ),
        **kwargs,
    )


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


@pytest.mark.parametrize(
    (
        "status_code",
        "expected_exception",
        "expected_status",
        "expected_error_type",
    ),
    [
        (408, LLMTimeout, "timeout", "LLMTimeout"),
        (429, LLMUnavailable, "error", "LLMUnavailable"),
        (503, LLMUnavailable, "error", "LLMUnavailable"),
        (400, LLMProtocolError, "error", "LLMProtocolError"),
    ],
)
async def test_http_failure_translates_and_records_attempt_metadata(
    status_code: int,
    expected_exception: type[Exception],
    expected_status: str,
    expected_error_type: str,
) -> None:
    events: list[ProviderAttemptEvent] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"message": "boom"}})

    gateway = _client(
        httpx.MockTransport(handler),
        on_provider_attempt=events.append,
    )
    with pytest.raises(expected_exception):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )
    assert len(events) == 1
    assert events[0].attempt == "initial"
    assert events[0].status == expected_status
    assert events[0].error_type == expected_error_type


def _structured_completion(content: str) -> dict[str, object]:
    return {
        "id": "1",
        "object": "chat.completion",
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "index": 0,
            }
        ],
    }


async def test_structured_http_error_makes_exactly_one_physical_request() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(503, json={"error": {"message": "boom"}})

    gateway = _client(httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )
    assert calls["count"] == 1


async def test_structured_connection_error_makes_exactly_one_physical_request() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectError("refused", request=request)

    gateway = _client(httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )
    assert calls["count"] == 1


async def test_structured_cancellation_makes_exactly_one_physical_request() -> None:
    calls = {"count": 0}
    entered = asyncio.Event()

    class _HangingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("hanging request should have been cancelled")

    gateway = _client(_HangingTransport())
    task = asyncio.create_task(
        gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=5.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls["count"] == 1


async def test_structured_provider_error_on_correction_makes_exactly_two_physical_requests() -> (
    None
):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, json=_structured_completion('{"value":1}'))
        return httpx.Response(503, json={"error": {"message": "boom"}})

    gateway = _client(httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )
    assert calls["count"] == 2


async def test_provider_attempt_event_records_empty_content_correction_metadata() -> (
    None
):
    events: list[ProviderAttemptEvent] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": ""},
                        "index": 0,
                    }
                ],
            },
        )

    gateway = _client(
        httpx.MockTransport(handler),
        on_provider_attempt=events.append,
    )
    with pytest.raises(InvalidLLMOutput):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )
    assert [event.attempt for event in events] == ["initial", "correction"]
    assert all(event.status == "error" for event in events)
    assert all(event.error_type == "InvalidLLMOutput" for event in events)
    assert events[0].correction_trigger is None
    assert events[1].correction_trigger == "syntactic_or_schema_validation"


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


async def test_semantic_validator_failure_on_correction_raises_without_third_request() -> (
    None
):
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
                        "message": {
                            "role": "assistant",
                            "content": '{"value":"bad"}',
                        },
                        "index": 0,
                    }
                ],
            },
        )

    def validator(result: _Answer) -> _Answer:
        raise ValueError("semantic mismatch")

    gateway = _client(httpx.MockTransport(handler))
    with pytest.raises(InvalidLLMOutput):
        await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
            validate_result=validator,
        )
    assert calls["count"] == 2


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


async def test_thinking_prefill_applies_only_to_prompt_structured_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JUNG_LLM_THINKING_PREFILL", "1")
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
        _policy(mode=StructuredOutputMode.JSON_SCHEMA),
    )
    schema_body = captured["body"]
    assert isinstance(schema_body, dict)
    schema_messages = schema_body["messages"]
    assert isinstance(schema_messages, list)
    assert schema_messages[-1] != {"role": "assistant", "content": " \n"}

    await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="give json")],
        _Answer,
        _policy(mode=StructuredOutputMode.PROMPT),
    )
    prompt_body = captured["body"]
    assert isinstance(prompt_body, dict)
    prompt_messages = prompt_body["messages"]
    assert isinstance(prompt_messages, list)
    assert prompt_messages[-1] == {"role": "assistant", "content": " \n"}


async def test_default_client_accepts_empty_api_key() -> None:
    gateway = OpenAICompatibleLLM(
        AdapterConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="",
        )
    )
    await gateway.aclose()


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
            task_extra_body={
                LLMTask.ASSESSMENT: {"response_format": {"type": "json_object"}}
            },
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
    with pytest.raises(
        ValueError, match="extra_body cannot override adapter-owned fields"
    ):
        OpenAICompatibleLLM(config)


async def test_default_client_disables_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class StubClient:
        async def close(self) -> None:
            pass

    def capture_openai(*_args: object, **kwargs: object) -> StubClient:
        captured.update(kwargs)
        return StubClient()

    monkeypatch.setattr("jung.llm.openai_compatible.AsyncOpenAI", capture_openai)
    gateway = OpenAICompatibleLLM(
        AdapterConfig(
            base_url="http://testserver/v1",
            api_key="test",
        )
    )
    assert captured["max_retries"] == 0
    await gateway.aclose()


async def test_extra_body_rejects_forbidden_global_field_before_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_openai(*args: object, **kwargs: object) -> None:
        raise AssertionError("AsyncOpenAI must not be constructed")

    monkeypatch.setattr("jung.llm.openai_compatible.AsyncOpenAI", fail_openai)
    config = AdapterConfig(
        base_url="http://testserver/v1",
        api_key="test",
        extra_body={"model": "override"},
    )
    with pytest.raises(
        ValueError, match="extra_body cannot override adapter-owned fields"
    ):
        OpenAICompatibleLLM(config)


async def test_extra_body_rejects_forbidden_task_field_before_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_openai(*args: object, **kwargs: object) -> None:
        raise AssertionError("AsyncOpenAI must not be constructed")

    monkeypatch.setattr("jung.llm.openai_compatible.AsyncOpenAI", fail_openai)
    config = AdapterConfig(
        base_url="http://testserver/v1",
        api_key="test",
        task_extra_body={LLMTask.ASSESSMENT: {"stream": True}},
    )
    with pytest.raises(
        ValueError, match="extra_body cannot override adapter-owned fields"
    ):
        OpenAICompatibleLLM(config)


async def test_extra_body_task_replaces_global_object_without_deep_merge() -> None:
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

    config = AdapterConfig(
        base_url="http://testserver/v1",
        api_key="test",
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": True,
                "reasoning_budget": 1024,
            }
        },
        task_extra_body={
            LLMTask.ASSESSMENT: {
                "chat_template_kwargs": {
                    "enable_thinking": False,
                }
            }
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
    assert body.get("chat_template_kwargs") == {
        "enable_thinking": False,
    }
    assert "reasoning_budget" not in body.get("chat_template_kwargs", {})


async def test_extra_body_unrelated_global_keys_survive_task_override() -> None:
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

    config = AdapterConfig(
        base_url="http://testserver/v1",
        api_key="test",
        extra_body={"thinking": True, "shared": "global"},
        task_extra_body={
            LLMTask.ASSESSMENT: {
                "shared": "task",
                "reasoning_effort": "low",
            }
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
    assert body.get("thinking") is True
    assert body.get("shared") == "task"
    assert body.get("reasoning_effort") == "low"


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


class _HostileStrError(RuntimeError):
    def __str__(self) -> str:
        raise RuntimeError("broken exception message")


class _HostileAPIStatusError(APIStatusError):
    def __str__(self) -> str:
        raise RuntimeError("broken exception message")


def _hostile_api_status_error(status_code: int) -> APIStatusError:
    response = httpx.Response(
        status_code,
        request=httpx.Request("POST", "http://testserver/v1/chat/completions"),
    )
    return _HostileAPIStatusError("status failed", response=response, body=None)


@pytest.mark.parametrize(
    ("status_code", "expected_type"),
    [
        (408, LLMTimeout),
        (429, LLMUnavailable),
        (500, LLMUnavailable),
        (400, LLMProtocolError),
    ],
)
async def test_classify_status_error_uses_safe_exception_message(
    status_code: int,
    expected_type: type[Exception],
) -> None:
    from jung.llm.openai_compatible import _classify_status_error

    classified = _classify_status_error(_hostile_api_status_error(status_code))
    assert isinstance(classified, expected_type)
    assert str(classified) == "<exception message unavailable>"


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


async def test_validator_invalid_llm_output_records_semantic_correction_trigger() -> (
    None
):
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


async def test_stream_diagnostics_buffer_only_when_recorder_enabled(
    tmp_path: Path,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    chunk = json.dumps(
        {
            "id": "1",
            "object": "chat.completion.chunk",
            "choices": [
                {"delta": {"content": "hello"}, "index": 0, "finish_reason": None}
            ],
        }
    )
    final = json.dumps(
        {
            "id": "1",
            "object": "chat.completion.chunk",
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
        }
    )
    sse_body = f"data: {chunk}\n\ndata: {final}\n\ndata: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=sse_body,
            headers={"content-type": "text/event-stream"},
        )

    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="test-model",
        temperature=0.7,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )
    events: list[ProviderAttemptEvent] = []
    plain = _client(httpx.MockTransport(handler), on_provider_attempt=events.append)
    chunks = [
        piece
        async for piece in plain.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            policy,
        )
    ]
    assert "".join(chunks) == "hello"
    assert len(events) == 1
    assert events[0].response_chars is None

    with DiagnosticRecorder(tmp_path / "llm-stream") as recorder:
        observed = ObservedLLMGateway(
            _client(httpx.MockTransport(handler), recorder=recorder),
            recorder=recorder,
        )
        chunks = [
            piece
            async for piece in observed.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                policy,
            )
        ]
        assert "".join(chunks) == "hello"

    lines = [
        json.loads(line)
        for line in (tmp_path / "llm-stream" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    kinds = [entry["kind"] for entry in lines]
    assert "llm.provider.request" in kinds
    assert "llm.provider.response" in kinds
    assert "llm.output.accepted" not in kinds
    response = next(
        entry for entry in lines if entry["kind"] == "llm.provider.response"
    )
    assert response["data"]["raw_response_text"] == "hello"
    assert "llm.call.complete" not in kinds


async def test_structured_diagnostics_capture_request_and_validated_result(
    tmp_path: Path,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"value":"ok"}',
                        },
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    with DiagnosticRecorder(tmp_path / "llm-structured") as recorder:
        gateway = ObservedLLMGateway(
            _client(httpx.MockTransport(handler), recorder=recorder),
            recorder=recorder,
        )
        result = await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )
        assert result.value == "ok"

    lines = [
        json.loads(line)
        for line in (tmp_path / "llm-structured" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    kinds = [entry["kind"] for entry in lines]
    assert "llm.provider.request" in kinds
    assert "llm.provider.response" in kinds
    assert "llm.output.accepted" in kinds
    request = next(entry for entry in lines if entry["kind"] == "llm.provider.request")
    assert request["data"]["messages"][0]["content"] == "give json"
    assert "api_key" not in json.dumps(request)
    response = next(
        entry for entry in lines if entry["kind"] == "llm.provider.response"
    )
    assert response["data"]["raw_response_text"] == '{"value":"ok"}'
    assert response["data"]["prompt_tokens"] == 3
    assert response["data"]["completion_tokens"] == 2
    assert request["data"]["max_completion_tokens"] is None
    accepted = next(entry for entry in lines if entry["kind"] == "llm.output.accepted")
    assert accepted["data"]["result"]["value"] == "ok"
    assert accepted["data"]["output_type"] == "_Answer"
    assert "llm_call_id" in accepted["context"]


def _assert_one_terminal(
    events: list[dict[str, object]],
    *,
    start_kind: str,
    terminal_kinds: set[str],
    id_field: str,
) -> None:
    starts = [event for event in events if event["kind"] == start_kind]
    for start in starts:
        call_id = start["data"].get(id_field) or start["data"].get("call_id")
        terminals = [
            event
            for event in events
            if event["kind"] in terminal_kinds
            and (
                event["data"].get(id_field) == call_id
                or event["data"].get("call_id") == call_id
            )
        ]
        assert len(terminals) == 1, (start_kind, call_id, terminals)


async def test_unexpected_provider_error_records_provider_and_gateway_terminals(
    tmp_path: Path,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    with DiagnosticRecorder(tmp_path / "unexpected") as recorder:
        inner = _client(
            httpx.MockTransport(lambda request: httpx.Response(500)),
            recorder=recorder,
        )

        async def boom(**_kwargs: object) -> object:
            raise _UnexpectedProviderBug("sdk defect")

        inner._client.chat.completions.create = boom  # type: ignore[method-assign]
        gateway = ObservedLLMGateway(inner, recorder=recorder)
        with pytest.raises(_UnexpectedProviderBug, match="sdk defect"):
            await gateway.generate_structured(
                [ChatMessage(role=ChatRole.USER, content="give json")],
                _Answer,
                _policy(),
            )

    lines = [
        json.loads(line)
        for line in (tmp_path / "unexpected" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    _assert_one_terminal(
        lines,
        start_kind="llm.provider.request",
        terminal_kinds={"llm.provider.response", "llm.provider.error"},
        id_field="provider_attempt_id",
    )
    error = next(entry for entry in lines if entry["kind"] == "llm.provider.error")
    assert error["data"]["error_type"] == "_UnexpectedProviderBug"
    assert "sdk defect" in error["data"]["error_message"]
    started = [e for e in lines if e["kind"] == "llm.call.started"]
    failed = [e for e in lines if e["kind"] == "llm.call.failed"]
    assert len(started) == 1
    assert len(failed) == 1
    assert failed[0]["data"]["error_type"] == "_UnexpectedProviderBug"


async def test_hostile_str_provider_error_records_safe_message_structured(
    tmp_path: Path,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    with DiagnosticRecorder(tmp_path / "hostile-structured") as recorder:
        inner = _client(
            httpx.MockTransport(lambda request: httpx.Response(500)),
            recorder=recorder,
        )

        async def boom(**_kwargs: object) -> object:
            raise _HostileStrError()

        inner._client.chat.completions.create = boom  # type: ignore[method-assign]
        gateway = ObservedLLMGateway(inner, recorder=recorder)
        with pytest.raises(_HostileStrError):
            await gateway.generate_structured(
                [ChatMessage(role=ChatRole.USER, content="give json")],
                _Answer,
                _policy(),
            )

    lines = [
        json.loads(line)
        for line in (tmp_path / "hostile-structured" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    _assert_one_terminal(
        lines,
        start_kind="llm.provider.request",
        terminal_kinds={"llm.provider.response", "llm.provider.error"},
        id_field="provider_attempt_id",
    )
    error = next(entry for entry in lines if entry["kind"] == "llm.provider.error")
    assert error["data"]["error_type"] == "_HostileStrError"
    assert error["data"]["error_message"] == "<exception message unavailable>"


async def test_hostile_str_provider_error_records_safe_message_stream(
    tmp_path: Path,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    with DiagnosticRecorder(tmp_path / "hostile-stream") as recorder:
        inner = _client(
            httpx.MockTransport(lambda request: httpx.Response(500)),
            recorder=recorder,
        )

        async def boom(**_kwargs: object) -> object:
            raise _HostileStrError()

        inner._client.chat.completions.create = boom  # type: ignore[method-assign]
        gateway = ObservedLLMGateway(inner, recorder=recorder)
        with pytest.raises(_HostileStrError):
            async for _ in gateway.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hello")],
                _policy(mode=StructuredOutputMode.PROMPT),
            ):
                pass

    lines = [
        json.loads(line)
        for line in (tmp_path / "hostile-stream" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    _assert_one_terminal(
        lines,
        start_kind="llm.provider.request",
        terminal_kinds={"llm.provider.response", "llm.provider.error"},
        id_field="provider_attempt_id",
    )
    error = next(entry for entry in lines if entry["kind"] == "llm.provider.error")
    assert error["data"]["error_type"] == "_HostileStrError"
    assert error["data"]["error_message"] == "<exception message unavailable>"


async def test_stream_early_aclose_emits_abandoned_terminals(tmp_path: Path) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    chunk = json.dumps(
        {
            "id": "1",
            "object": "chat.completion.chunk",
            "choices": [
                {"delta": {"content": "hello"}, "index": 0, "finish_reason": None}
            ],
        }
    )
    hang = json.dumps(
        {
            "id": "1",
            "object": "chat.completion.chunk",
            "choices": [
                {"delta": {"content": " world"}, "index": 0, "finish_reason": None}
            ],
        }
    )
    sse_body = f"data: {chunk}\n\ndata: {hang}\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=sse_body,
            headers={"content-type": "text/event-stream"},
        )

    with DiagnosticRecorder(tmp_path / "abandoned") as recorder:
        gateway = ObservedLLMGateway(
            _client(httpx.MockTransport(handler), recorder=recorder),
            recorder=recorder,
        )
        stream = gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            _policy(mode=StructuredOutputMode.PROMPT),
        )
        first = await stream.__anext__()
        assert first == "hello"
        await stream.aclose()

    lines = [
        json.loads(line)
        for line in (tmp_path / "abandoned" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    provider_error = next(
        entry for entry in lines if entry["kind"] == "llm.provider.error"
    )
    assert provider_error["data"]["status"] == "abandoned"
    _assert_one_terminal(
        lines,
        start_kind="llm.provider.request",
        terminal_kinds={"llm.provider.response", "llm.provider.error"},
        id_field="provider_attempt_id",
    )


async def test_stream_early_aclose_closes_sdk_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    class _Delta:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str) -> None:
            self.delta = _Delta(content)
            self.finish_reason = None

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    class FakeSDKStream:
        def __init__(self) -> None:
            self._sent = False
            self.aclose_called = 0

        def __aiter__(self) -> FakeSDKStream:
            return self

        async def __anext__(self) -> _Chunk:
            if self._sent:
                # Keep yielding until the generator is closed.
                await asyncio.sleep(10.0)
                raise AssertionError("unreachable")
            self._sent = True
            return _Chunk("hello")

        async def aclose(self) -> None:
            self.aclose_called += 1

    async def fake_create(**kwargs: object) -> FakeSDKStream:
        return sdk_stream

    sdk_stream = FakeSDKStream()

    def handler(request: httpx.Request) -> httpx.Response:
        # Not used: we monkeypatch the SDK create() to return FakeSDKStream.
        return httpx.Response(500, content=b"unused")

    with DiagnosticRecorder(tmp_path / "sdk-close") as recorder:
        gateway = _client(httpx.MockTransport(handler), recorder=recorder)
        monkeypatch.setattr(
            gateway._client.chat.completions,  # type: ignore[attr-defined]
            "create",
            fake_create,
        )
        observed = ObservedLLMGateway(gateway, recorder=recorder)
        stream = observed.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            _policy(mode=StructuredOutputMode.PROMPT),
        )

        first = await stream.__anext__()
        assert first == "hello"
        await stream.aclose()

        assert sdk_stream.aclose_called == 1

    lines = [
        json.loads(line)
        for line in (tmp_path / "sdk-close" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    provider_error = next(
        entry for entry in lines if entry["kind"] == "llm.provider.error"
    )
    assert provider_error["data"]["status"] == "abandoned"


async def test_sdk_stream_close_cancellederror_is_swallowed_and_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    class _Delta:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str) -> None:
            self.delta = _Delta(content)
            self.finish_reason = None

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    class FakeSDKStream:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self) -> FakeSDKStream:
            return self

        async def __anext__(self) -> _Chunk:
            if self._sent:
                raise StopAsyncIteration
            self._sent = True
            return _Chunk("hello")

        async def aclose(self) -> None:
            raise asyncio.CancelledError()

    async def fake_create(**kwargs: object) -> FakeSDKStream:
        return sdk_stream

    sdk_stream = FakeSDKStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"unused")

    with DiagnosticRecorder(tmp_path / "sdk-close-cancel") as recorder:
        gateway = _client(httpx.MockTransport(handler), recorder=recorder)
        monkeypatch.setattr(
            gateway._client.chat.completions,  # type: ignore[attr-defined]
            "create",
            fake_create,
        )
        observed = ObservedLLMGateway(gateway, recorder=recorder)

        with caplog.at_level(logging.WARNING):
            chunks = []
            async for chunk in observed.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                _policy(mode=StructuredOutputMode.PROMPT),
            ):
                chunks.append(chunk)
            assert chunks == ["hello"]

    lines = [
        json.loads(line)
        for line in (tmp_path / "sdk-close-cancel" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert not any(e["kind"] == "llm.provider.cleanup.error" for e in lines)
    assert any("llm provider stream close failed" in r.message for r in caplog.records)
    call_errors = [e for e in lines if e["kind"] == "llm.provider.error"]
    assert not call_errors


async def test_stream_task_cancellation_emits_cancelled_terminals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    class _Delta:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str) -> None:
            self.delta = _Delta(content)
            self.finish_reason = None

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    first_yielded = asyncio.Event()
    block_next = asyncio.Event()

    class FakeSDKStream:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self) -> FakeSDKStream:
            return self

        async def __anext__(self) -> _Chunk:
            if not self._sent:
                self._sent = True
                first_yielded.set()
                return _Chunk("hello")
            await block_next.wait()
            return _Chunk("world")

        async def aclose(self) -> None:
            return None

    sdk_stream = FakeSDKStream()

    async def fake_create(**kwargs: object) -> FakeSDKStream:
        return sdk_stream

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"unused")

    with DiagnosticRecorder(tmp_path / "cancel-terminals") as recorder:
        gateway = _client(httpx.MockTransport(handler), recorder=recorder)
        monkeypatch.setattr(
            gateway._client.chat.completions,  # type: ignore[attr-defined]
            "create",
            fake_create,
        )
        observed = ObservedLLMGateway(gateway, recorder=recorder)

        async def consume() -> None:
            async for _chunk in observed.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                _policy(mode=StructuredOutputMode.PROMPT),
            ):
                pass

        task = asyncio.create_task(consume())
        await first_yielded.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    lines = [
        json.loads(line)
        for line in (tmp_path / "cancel-terminals" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    provider_errors = [
        e
        for e in lines
        if e["kind"] == "llm.provider.error" and e["data"]["status"] == "cancelled"
    ]
    assert len(provider_errors) == 1
    assert provider_errors[0]["context"].get("llm_call_id") or provider_errors[0][
        "data"
    ].get("llm_call_id")


async def test_stream_preserves_stream_cancel_message_over_close_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    class _Delta:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str) -> None:
            self.delta = _Delta(content)
            self.finish_reason = None

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    first_yielded = asyncio.Event()
    close_started = asyncio.Event()
    close_release = asyncio.Event()
    close_finished = asyncio.Event()

    class FakeSDKStream:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self) -> FakeSDKStream:
            return self

        async def __anext__(self) -> _Chunk:
            if not self._sent:
                self._sent = True
                first_yielded.set()
                return _Chunk("hello")
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def aclose(self) -> None:
            close_started.set()
            try:
                await close_release.wait()
            finally:
                close_finished.set()

    sdk_stream = FakeSDKStream()

    async def fake_create(**kwargs: object) -> FakeSDKStream:
        return sdk_stream

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"unused")

    with DiagnosticRecorder(tmp_path / "preserve-stream-cancel") as recorder:
        gateway = _client(httpx.MockTransport(handler), recorder=recorder)
        monkeypatch.setattr(
            gateway._client.chat.completions,  # type: ignore[attr-defined]
            "create",
            fake_create,
        )
        observed = ObservedLLMGateway(gateway, recorder=recorder)

        async def consume() -> None:
            async for _chunk in observed.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                _policy(mode=StructuredOutputMode.PROMPT),
            ):
                pass

        task = asyncio.create_task(consume())
        await first_yielded.wait()
        task.cancel("stream-cancel")
        await close_started.wait()
        task.cancel("close-cancel")
        await asyncio.sleep(0.01)
        assert not task.done()
        close_release.set()
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task
        assert exc_info.value.args == ("stream-cancel",)
        assert close_finished.is_set() is True

    lines = [
        json.loads(line)
        for line in (tmp_path / "preserve-stream-cancel" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    provider_requests = [e for e in lines if e["kind"] == "llm.provider.request"]
    assert len(provider_requests) == 1
    call_id = provider_requests[0]["data"]["llm_call_id"]
    provider_attempt_id = provider_requests[0]["data"]["provider_attempt_id"]
    provider_terminals = [
        e
        for e in lines
        if e["kind"] in {"llm.provider.response", "llm.provider.error"}
        and e["data"].get("provider_attempt_id") == provider_attempt_id
    ]
    assert len(provider_terminals) == 1
    assert provider_terminals[0]["data"]["status"] == "cancelled"
    assert provider_terminals[0]["data"]["llm_call_id"] == call_id
    assert not any(e["kind"] == "llm.provider.cleanup.error" for e in lines)
    assert not any(e["kind"] == "llm.stream.cleanup.error" for e in lines)


async def test_stream_cancel_with_close_cancellederror_keeps_single_terminals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    class _Delta:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str) -> None:
            self.delta = _Delta(content)
            self.finish_reason = None

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    first_yielded = asyncio.Event()

    class FakeSDKStream:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self) -> FakeSDKStream:
            return self

        async def __anext__(self) -> _Chunk:
            if not self._sent:
                self._sent = True
                first_yielded.set()
                return _Chunk("hello")
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def aclose(self) -> None:
            raise asyncio.CancelledError("close-own-cancel")

    sdk_stream = FakeSDKStream()

    async def fake_create(**kwargs: object) -> FakeSDKStream:
        return sdk_stream

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"unused")

    with DiagnosticRecorder(tmp_path / "cancel-plus-close-cancel") as recorder:
        gateway = _client(httpx.MockTransport(handler), recorder=recorder)
        monkeypatch.setattr(
            gateway._client.chat.completions,  # type: ignore[attr-defined]
            "create",
            fake_create,
        )
        observed = ObservedLLMGateway(gateway, recorder=recorder)

        async def consume() -> None:
            async for _chunk in observed.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                _policy(mode=StructuredOutputMode.PROMPT),
            ):
                pass

        task = asyncio.create_task(consume())
        await first_yielded.wait()
        task.cancel("stream-cancel")
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task
        assert exc_info.value.args == ("stream-cancel",)

    lines = [
        json.loads(line)
        for line in (tmp_path / "cancel-plus-close-cancel" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    provider_requests = [e for e in lines if e["kind"] == "llm.provider.request"]
    assert len(provider_requests) == 1
    provider_attempt_id = provider_requests[0]["data"]["provider_attempt_id"]
    provider_terminals = [
        e
        for e in lines
        if e["kind"] in {"llm.provider.response", "llm.provider.error"}
        and e["data"].get("provider_attempt_id") == provider_attempt_id
    ]
    assert len(provider_terminals) == 1
    assert provider_terminals[0]["data"]["status"] == "cancelled"
    assert not any(e["kind"] == "llm.provider.cleanup.error" for e in lines)


async def test_provider_close_failure_without_recorder_logs_safe_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Delta:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str) -> None:
            self.delta = _Delta(content)
            self.finish_reason = None

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    class FakeSDKStream:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self) -> FakeSDKStream:
            return self

        async def __anext__(self) -> _Chunk:
            if self._sent:
                raise StopAsyncIteration
            self._sent = True
            return _Chunk("hello")

        async def aclose(self) -> None:
            raise RuntimeError(
                "close boom secret=sk-provider-leak url=https://user:pass@host/path"
            )

    sdk_stream = FakeSDKStream()

    async def fake_create(**kwargs: object) -> FakeSDKStream:
        return sdk_stream

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"unused")

    gateway = _client(httpx.MockTransport(handler), recorder=None)
    monkeypatch.setattr(
        gateway._client.chat.completions,  # type: ignore[attr-defined]
        "create",
        fake_create,
    )

    with caplog.at_level(logging.WARNING, logger="jung.llm.openai_compatible"):
        chunks: list[str] = []
        async for chunk in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            _policy(mode=StructuredOutputMode.PROMPT),
        ):
            chunks.append(chunk)

    assert chunks == ["hello"]
    warnings = [
        record
        for record in caplog.records
        if "llm provider stream close failed" in record.getMessage()
    ]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "error_type=RuntimeError" in message
    assert "close_method=aclose" in message
    assert "sk-provider-leak" not in message
    assert "close boom" not in message
    assert "user:pass" not in message
    assert "https://" not in message


async def test_early_aclose_ambient_cancel_emits_abandoned_terminals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    class _Delta:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str) -> None:
            self.delta = _Delta(content)
            self.finish_reason = None

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    close_started = asyncio.Event()
    close_release = asyncio.Event()
    close_finished = asyncio.Event()

    class FakeSDKStream:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self) -> FakeSDKStream:
            return self

        async def __anext__(self) -> _Chunk:
            if self._sent:
                raise StopAsyncIteration
            self._sent = True
            return _Chunk("hello")

        async def aclose(self) -> None:
            close_started.set()
            try:
                await close_release.wait()
            finally:
                close_finished.set()

    sdk_stream = FakeSDKStream()

    async def fake_create(**kwargs: object) -> FakeSDKStream:
        return sdk_stream

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"unused")

    attempts: list[ProviderAttemptEvent] = []

    with DiagnosticRecorder(tmp_path / "early-aclose-cancel") as recorder:
        gateway = _client(
            httpx.MockTransport(handler),
            on_provider_attempt=attempts.append,
            recorder=recorder,
        )
        monkeypatch.setattr(
            gateway._client.chat.completions,  # type: ignore[attr-defined]
            "create",
            fake_create,
        )
        observed = ObservedLLMGateway(gateway, recorder=recorder)

        async def consume() -> None:
            stream = observed.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                _policy(mode=StructuredOutputMode.PROMPT),
            )
            first = await stream.__anext__()
            assert first == "hello"
            await stream.aclose()

        close_task = asyncio.create_task(consume())
        await close_started.wait()
        close_task.cancel()
        await asyncio.sleep(0.01)
        assert not close_task.done()
        close_release.set()
        with pytest.raises(asyncio.CancelledError):
            await close_task
        assert close_finished.is_set() is True

    trace_path = tmp_path / "early-aclose-cancel" / "trace.jsonl"
    lines = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    def only(kind: str) -> dict[str, object]:
        matches = [e for e in lines if e["kind"] == kind]
        assert len(matches) == 1, f"expected exactly one {kind}"
        return matches[0]

    provider_start = only("llm.provider.request")
    provider_terminals = [
        e
        for e in lines
        if e["kind"] in {"llm.provider.response", "llm.provider.error"}
        and e["data"].get("provider_attempt_id")
        == provider_start["data"]["provider_attempt_id"]
    ]
    assert len(provider_terminals) == 1
    assert provider_terminals[0]["kind"] == "llm.provider.error"
    assert provider_terminals[0]["data"]["status"] == "abandoned"
    assert provider_start["data"]["llm_call_id"]

    assert len(attempts) == 1
    assert attempts[0].status == "abandoned"

    state_after_exit = (
        trace_path.stat().st_size,
        trace_path.stat().st_mtime_ns,
        len(lines),
    )
    await asyncio.sleep(0.05)
    reparsed = [
        line
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert (
        trace_path.stat().st_size,
        trace_path.stat().st_mtime_ns,
        len(reparsed),
    ) == state_after_exit


async def test_structured_validation_failure_then_correction_success(
    tmp_path: Path,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        content = "not-json" if calls["n"] == 1 else '{"value":"ok"}'
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
            },
        )

    with DiagnosticRecorder(tmp_path / "correction-ok") as recorder:
        gateway = ObservedLLMGateway(
            _client(httpx.MockTransport(handler), recorder=recorder),
            recorder=recorder,
        )
        result = await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="give json")],
            _Answer,
            _policy(),
        )
        assert result.value == "ok"

    kinds = [
        json.loads(line)["kind"]
        for line in (tmp_path / "correction-ok" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert "llm.call.started" in kinds
    assert "llm.validation.failed" in kinds
    assert "llm.correction.started" in kinds
    assert "llm.output.accepted" in kinds
    assert "llm.call.completed" in kinds
    assert "llm.call.failed" not in kinds


async def test_structured_double_validation_failure(tmp_path: Path) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "not-json"},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
            },
        )

    with DiagnosticRecorder(tmp_path / "correction-fail") as recorder:
        gateway = ObservedLLMGateway(
            _client(httpx.MockTransport(handler), recorder=recorder),
            recorder=recorder,
        )
        with pytest.raises(InvalidLLMOutput):
            await gateway.generate_structured(
                [ChatMessage(role=ChatRole.USER, content="give json")],
                _Answer,
                _policy(),
            )

    kinds = [
        json.loads(line)["kind"]
        for line in (tmp_path / "correction-fail" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert kinds.count("llm.validation.failed") == 2
    assert "llm.correction.started" in kinds
    assert "llm.call.failed" in kinds
    assert "llm.call.completed" not in kinds
    assert "llm.output.accepted" not in kinds


async def test_stream_aclose_records_consumer_closed_cancellation(
    tmp_path: Path,
) -> None:
    from jung.diagnostics import DiagnosticRecorder
    from jung.llm.tracing import ObservedLLMGateway

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"id":"1","object":"chat.completion.chunk","choices":'
                b'[{"delta":{"content":"he"},"index":0}]}\n\n'
                b'data: {"id":"1","object":"chat.completion.chunk","choices":'
                b'[{"delta":{"content":"llo"},"index":0}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    with DiagnosticRecorder(tmp_path / "stream-aclose") as recorder:
        gateway = ObservedLLMGateway(
            _client(httpx.MockTransport(handler), recorder=recorder),
            recorder=recorder,
        )
        stream = gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            _policy(),
        )
        first = await stream.__anext__()
        assert first
        await stream.aclose()

    events = [
        json.loads(line)
        for line in (tmp_path / "stream-aclose" / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    started = [e for e in events if e["kind"] == "llm.call.started"]
    cancelled = [e for e in events if e["kind"] == "llm.call.cancelled"]
    assert len(started) == 1
    assert len(cancelled) == 1
    assert cancelled[0]["data"]["reason"] == "consumer_closed"
    assert not any(e["kind"] == "llm.call.completed" for e in events)
    assert not any(e["kind"] == "llm.call.failed" for e in events)
