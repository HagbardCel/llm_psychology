from __future__ import annotations

import pytest
import trio
import trio.testing

from exceptions import LLMServiceError
from services.llm_service import LLMService, TrioRateLimiter


class _FakeChatModel:
    def __init__(self) -> None:
        self.invoke_calls: list[list[object]] = []
        self.stream_calls: list[list[object]] = []
        self.with_structured_output_calls: list[tuple[object, str]] = []

        self.response_content: str = "fake response"
        self.raise_on_invoke: Exception | None = None
        self.stream_chunk_contents: list[str] = ["Hello ", "", "world!"]
        self.structured_result: object = {"ok": True}
        self.last_runnable: object | None = None

    def invoke(self, messages):
        self.invoke_calls.append(messages)
        if self.raise_on_invoke:
            raise self.raise_on_invoke
        return type("Resp", (), {"content": self.response_content})()

    def stream(self, messages):
        self.stream_calls.append(messages)
        for content in self.stream_chunk_contents:
            yield type("Chunk", (), {"content": content})()

    def with_structured_output(self, schema, method: str = "json_schema"):
        self.with_structured_output_calls.append((schema, method))

        parent = self

        class _Runnable:
            def __init__(self):
                self.invoke_calls: list[str] = []

            def invoke(self, prompt: str):
                self.invoke_calls.append(prompt)
                return parent.structured_result

        runnable = _Runnable()
        self.last_runnable = runnable
        return runnable


@pytest.fixture
def fake_chat_model(monkeypatch) -> _FakeChatModel:
    import services.llm_service as llm_module

    fake = _FakeChatModel()
    monkeypatch.setattr(
        llm_module,
        "ChatGoogleGenerativeAI",
        lambda **_kwargs: fake,
    )
    return fake


def test_generate_response_without_context_uses_human_message(fake_chat_model):
    from langchain_core.messages import HumanMessage

    service = LLMService(api_key="test", model_name="test-model", rate_limit_enabled=False)
    fake_chat_model.response_content = "ok"

    result = service.generate_response("Hello")
    assert result == "ok"

    assert len(fake_chat_model.invoke_calls) == 1
    messages = fake_chat_model.invoke_calls[0]
    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "Hello"


def test_generate_response_with_context_maps_roles(fake_chat_model):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    service = LLMService(api_key="test", model_name="test-model", rate_limit_enabled=False)
    fake_chat_model.response_content = "ok"

    context = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]

    result = service.generate_response("How are you?", context=context)
    assert result == "ok"

    assert len(fake_chat_model.invoke_calls) == 1
    messages = fake_chat_model.invoke_calls[0]
    assert [type(m) for m in messages] == [
        SystemMessage,
        HumanMessage,
        AIMessage,
        HumanMessage,
    ]
    assert messages[0].content == "You are helpful."
    assert messages[-1].content == "How are you?"


def test_generate_response_wraps_exceptions(fake_chat_model):
    service = LLMService(api_key="test", model_name="test-model", rate_limit_enabled=False)
    fake_chat_model.raise_on_invoke = RuntimeError("boom")

    with pytest.raises(LLMServiceError) as exc_info:
        service.generate_response("Hello")

    msg = str(exc_info.value)
    assert "LLM generation failed" in msg
    assert "STACKTRACE" in msg
    assert "RuntimeError" in msg


@pytest.mark.trio
async def test_generate_response_stream_collects_non_empty_chunks(fake_chat_model, monkeypatch):
    import services.llm_service as llm_module

    async def _run_sync(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(llm_module.trio.to_thread, "run_sync", _run_sync)

    service = LLMService(api_key="test", model_name="test-model", rate_limit_enabled=False)
    fake_chat_model.stream_chunk_contents = ["a", "", "b"]

    chunks = await service.generate_response_stream("Hello", context=None)
    assert chunks == ["a", "b"]

    assert len(fake_chat_model.stream_calls) == 1


def test_generate_structured_output_uses_with_structured_output(fake_chat_model):
    from pydantic import BaseModel

    class _Schema(BaseModel):
        ok: bool

    expected = _Schema(ok=True)
    fake_chat_model.structured_result = expected

    service = LLMService(api_key="test", model_name="test-model", rate_limit_enabled=False)
    result = service.generate_structured_output("prompt", _Schema)

    assert result == expected
    assert fake_chat_model.with_structured_output_calls == [(_Schema, "json_schema")]


def test_trio_rate_limiter_honors_capacity_and_rate():
    async def _main():
        limiter = TrioRateLimiter(rate=1.0, capacity=2.0)  # 1 token/sec, burst 2
        # Use up the burst without waiting.
        await limiter.acquire()
        await limiter.acquire()

        t0 = trio.current_time()
        await limiter.acquire()  # requires waiting ~1s for refill
        t1 = trio.current_time()

        assert t1 - t0 == pytest.approx(1.0, abs=1e-6)

    # Without auto-jumping, MockClock time does not advance and sleeps can hang.
    trio.run(_main, clock=trio.testing.MockClock(autojump_threshold=0.0))
