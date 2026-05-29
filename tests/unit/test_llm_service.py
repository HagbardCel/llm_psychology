from __future__ import annotations

import json

import pytest
import trio
import trio.testing

from psychoanalyst_app.exceptions import LLMServiceError
from psychoanalyst_app.services.llm_service import LLMService, TrioRateLimiter


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


class _FakeLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)


@pytest.fixture
def fake_chat_model(monkeypatch) -> _FakeChatModel:
    import psychoanalyst_app.services.llm_service as llm_module

    fake = _FakeChatModel()
    monkeypatch.setattr(
        llm_module,
        "ChatGoogleGenerativeAI",
        lambda **_kwargs: fake,
    )
    return fake


@pytest.fixture
def fake_llm_call_logger(monkeypatch) -> _FakeLogger:
    import psychoanalyst_app.services.llm_service as llm_module

    fake = _FakeLogger()
    monkeypatch.setattr(llm_module, "_get_llm_call_logger", lambda: fake)
    return fake


def test_generate_response_without_context_uses_human_message(fake_chat_model):
    from langchain_core.messages import HumanMessage

    service = LLMService(
        api_key="test",
        model_name="test-model",
        rate_limit_enabled=False,
    )
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

    service = LLMService(
        api_key="test",
        model_name="test-model",
        rate_limit_enabled=False,
    )
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
    service = LLMService(
        api_key="test",
        model_name="test-model",
        rate_limit_enabled=False,
    )
    fake_chat_model.raise_on_invoke = RuntimeError("boom")

    with pytest.raises(LLMServiceError) as exc_info:
        service.generate_response("Hello")

    msg = str(exc_info.value)
    assert "LLM generation failed" in msg
    assert "STACKTRACE" in msg
    assert "RuntimeError" in msg


@pytest.mark.trio
async def test_stream_response_yields_non_empty_chunks(fake_chat_model):
    service = LLMService(
        api_key="test",
        model_name="test-model",
        rate_limit_enabled=False,
    )
    fake_chat_model.stream_chunk_contents = ["a", "", "b"]

    chunks: list[str] = []
    async for chunk in service.stream_response("Hello", context=None):
        chunks.append(chunk)

    assert chunks == ["a", "b"]
    assert len(fake_chat_model.stream_calls) == 1


@pytest.mark.trio
async def test_generate_response_stream_collects_chunks(fake_chat_model):
    service = LLMService(
        api_key="test",
        model_name="test-model",
        rate_limit_enabled=False,
    )
    fake_chat_model.stream_chunk_contents = ["x", "y"]

    chunks = await service.generate_response_stream("Hello", context=None)
    assert chunks == ["x", "y"]


def test_generate_structured_output_uses_with_structured_output(fake_chat_model):
    from pydantic import BaseModel

    class _Schema(BaseModel):
        ok: bool

    expected = _Schema(ok=True)
    fake_chat_model.structured_result = expected

    service = LLMService(
        api_key="test",
        model_name="test-model",
        rate_limit_enabled=False,
    )
    result = service.generate_structured_output("prompt", _Schema)

    assert result == expected
    assert fake_chat_model.with_structured_output_calls == [(_Schema, "json_schema")]


def test_ollama_provider_builds_chat_ollama(monkeypatch):
    import psychoanalyst_app.services.llm_service as llm_module

    captured: dict[str, object] = {}

    def _fake_chat_ollama(**kwargs):
        captured.update(kwargs)
        return _FakeChatModel()

    monkeypatch.setattr(llm_module, "ChatOllama", _fake_chat_ollama)

    service = LLMService(
        provider="ollama",
        model_name="llama3.1",
        base_url="http://host.docker.internal:11434",
        rate_limit_enabled=False,
    )

    assert service.provider == "ollama"
    assert captured == {
        "model": "llama3.1",
        "temperature": 0.7,
        "base_url": "http://host.docker.internal:11434",
    }


def test_lmstudio_provider_builds_openai_compatible_client(monkeypatch):
    import psychoanalyst_app.services.llm_service as llm_module

    captured: dict[str, object] = {}

    def _fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return _FakeChatModel()

    monkeypatch.setattr(llm_module, "ChatOpenAI", _fake_chat_openai)

    service = LLMService(
        provider="lmstudio",
        model_name="local-model",
        base_url="http://host.docker.internal:1234/v1",
        rate_limit_enabled=False,
    )

    assert service.provider == "lmstudio"
    assert captured == {
        "model": "local-model",
        "api_key": "not-needed",
        "temperature": 0.7,
        "base_url": "http://host.docker.internal:1234/v1",
        "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
    }


def test_openai_compatible_provider_disables_thinking(monkeypatch):
    import psychoanalyst_app.services.llm_service as llm_module

    captured: dict[str, object] = {}

    def _fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return _FakeChatModel()

    monkeypatch.setattr(llm_module, "ChatOpenAI", _fake_chat_openai)

    service = LLMService(
        provider="openai_compatible",
        model_name="local-model",
        base_url="http://host.docker.internal:8080/v1",
        rate_limit_enabled=False,
        enable_thinking=False,
    )

    assert captured["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False},
    }
    assert "chat_template_kwargs" not in captured.get("model_kwargs", {})


def test_ollama_provider_does_not_send_thinking_kwargs(monkeypatch):
    import psychoanalyst_app.services.llm_service as llm_module

    captured: dict[str, object] = {}

    def _fake_chat_ollama(**kwargs):
        captured.update(kwargs)
        return _FakeChatModel()

    monkeypatch.setattr(llm_module, "ChatOllama", _fake_chat_ollama)

    LLMService(
        provider="ollama",
        model_name="llama3.1",
        base_url="http://host.docker.internal:11434",
        rate_limit_enabled=False,
        enable_thinking=False,
    )

    assert "model_kwargs" not in captured
    assert "extra_body" not in captured


def test_local_structured_output_parses_json(monkeypatch):
    from pydantic import BaseModel

    import psychoanalyst_app.services.llm_service as llm_module

    class _Schema(BaseModel):
        ok: bool

    fake = _FakeChatModel()
    fake.response_content = '```json\n{"ok": true}\n```'
    monkeypatch.setattr(llm_module, "ChatOllama", lambda **_kwargs: fake)

    service = LLMService(
        provider="ollama",
        model_name="llama3.1",
        rate_limit_enabled=False,
    )

    result = service.generate_structured_output("prompt", _Schema)

    assert result == _Schema(ok=True)
    assert fake.with_structured_output_calls == []
    assert len(fake.invoke_calls) == 1
    assert "Return only valid JSON" in fake.invoke_calls[0][0].content


def test_local_structured_output_invalid_json_raises(monkeypatch):
    from pydantic import BaseModel

    import psychoanalyst_app.services.llm_service as llm_module

    class _Schema(BaseModel):
        ok: bool

    fake = _FakeChatModel()
    fake.response_content = "not json"
    monkeypatch.setattr(llm_module, "ChatOllama", lambda **_kwargs: fake)

    service = LLMService(
        provider="ollama",
        model_name="llama3.1",
        rate_limit_enabled=False,
    )

    with pytest.raises(LLMServiceError, match="structured output parsing failed"):
        service.generate_structured_output("prompt", _Schema)


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


def test_llm_call_logging_disabled_by_default(
    fake_chat_model,
    fake_llm_call_logger,
):
    service = LLMService(
        api_key="test",
        model_name="test-model",
        rate_limit_enabled=False,
    )
    service._log_llm_call("request", {"prompt": "secret"})
    assert fake_llm_call_logger.messages == []


def test_llm_call_logging_redacts_payload_fields(
    fake_chat_model,
    fake_llm_call_logger,
):
    service = LLMService(
        api_key="test",
        model_name="test-model",
        rate_limit_enabled=False,
        llm_call_logging_enabled=True,
    )
    service._log_llm_call(
        "request",
        {
            "prompt": "sensitive prompt text",
            "context": [{"role": "user", "content": "private context"}],
        },
    )

    assert len(fake_llm_call_logger.messages) == 1
    record = json.loads(fake_llm_call_logger.messages[0])
    assert record["prompt"].startswith("<redacted len=")
    assert record["context"][0]["role"] == "user"
    assert record["context"][0]["content"].startswith("<redacted len=")


def test_llm_call_logging_skips_stream_chunks_by_default(
    fake_chat_model,
    fake_llm_call_logger,
):
    service = LLMService(
        api_key="test",
        model_name="test-model",
        rate_limit_enabled=False,
        llm_call_logging_enabled=True,
    )
    service._log_llm_call("stream_chunk", {"chunk": "hello"})
    assert fake_llm_call_logger.messages == []


def test_llm_call_logging_truncates_non_redacted_fields(
    fake_chat_model,
    fake_llm_call_logger,
):
    service = LLMService(
        api_key="test",
        model_name="test-model",
        rate_limit_enabled=False,
        llm_call_logging_enabled=True,
        llm_call_logging_redact=False,
        llm_call_logging_max_field_chars=64,
    )
    long_prompt = "a" * 90
    service._log_llm_call("request", {"prompt": long_prompt})

    assert len(fake_llm_call_logger.messages) == 1
    record = json.loads(fake_llm_call_logger.messages[0])
    assert record["prompt"].startswith("a" * 64)
    assert "<truncated" in record["prompt"]
