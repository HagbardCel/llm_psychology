"""Tests for OpenAI-compatible gateway with mocked transport."""

from __future__ import annotations

import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from jung.llm.errors import InvalidLLMOutput, LLMUnavailable
from jung.llm.gateway import (
    AdapterConfig,
    ChatMessage,
    ChatRole,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
)
from jung.llm.openai_compatible import OpenAICompatibleLLM


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


def _client(handler: httpx.MockTransport) -> OpenAICompatibleLLM:
    return OpenAICompatibleLLM(
        AdapterConfig(base_url="http://testserver/v1", api_key="test"),
        client=AsyncOpenAI(
            base_url="http://testserver/v1",
            api_key="test",
            http_client=httpx.AsyncClient(transport=handler),
            max_retries=0,
        ),
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
