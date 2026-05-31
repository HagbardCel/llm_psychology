from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import trio
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from psychoanalyst_app.exceptions import LLMQuotaExhaustedError, LLMServiceError
from psychoanalyst_app.utils.trio_streaming import iter_in_thread

logger = logging.getLogger(__name__)
LLM_CALL_LOGGER_NAME = "llm_calls"
LLM_METRICS_LOGGER_NAME = "llm_metrics"

try:
    from google.api_core.exceptions import ResourceExhausted
except Exception:  # pragma: no cover - optional import fallback
    ResourceExhausted = None

try:
    from langchain_ollama import ChatOllama
except Exception:  # pragma: no cover - optional dependency fallback
    ChatOllama = None

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional dependency fallback
    ChatOpenAI = None


SUPPORTED_LLM_PROVIDERS = {"gemini", "ollama", "lmstudio", "openai_compatible"}


def _get_llm_call_logger() -> logging.Logger:
    llm_logger = logging.getLogger(LLM_CALL_LOGGER_NAME)
    if not llm_logger.handlers:
        # Runtime handler setup is owned by config.setup_logging().
        # Keep a null handler here so logging remains a no-op unless enabled.
        llm_logger.addHandler(logging.NullHandler())
    llm_logger.propagate = False
    return llm_logger


class TrioRateLimiter:
    """Token bucket rate limiter for Trio applications.

    This rate limiter uses the token bucket algorithm to control the rate
    of operations. It allows for burst traffic up to the capacity limit
    while ensuring the average rate stays within the specified limit.

    Attributes:
        rate: Tokens refilled per second
        capacity: Maximum number of tokens (burst capacity)
    """

    def __init__(self, rate: float, capacity: float):
        """Initialize the rate limiter.

        Args:
            rate: Tokens per second (e.g., 5/60 = 0.083 for 5 req/min)
            capacity: Maximum burst tokens (max concurrent requests)
        """
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        # Initialized lazily in `acquire()` because `trio.current_time()` requires
        # an active async context.
        self._last_update: float | None = None
        self._lock = trio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire tokens, waiting if necessary.

        This method will block until enough tokens are available.
        Tokens are refilled continuously based on the configured rate.

        Args:
            tokens: Number of tokens to acquire (default: 1.0)
        """
        async with self._lock:
            if self._last_update is None:
                self._last_update = trio.current_time()
            while True:
                # Refill tokens based on elapsed time
                now = trio.current_time()
                elapsed = now - self._last_update
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last_update = now

                if self._tokens >= tokens:
                    # Enough tokens available
                    self._tokens -= tokens
                    return

                # Not enough tokens, wait for next refill
                wait_time = (tokens - self._tokens) / self.rate
                logger.debug(
                    f"Rate limit: waiting {wait_time:.2f}s "
                    f"(tokens: {self._tokens:.2f}/{self.capacity})"
                )
                await trio.sleep(wait_time)


class LLMService:
    """Service for handling LLM API calls with rate limiting."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "",
        api_keys: list[str] | None = None,
        provider: str = "gemini",
        base_url: str | None = None,
        rate_limit_enabled: bool = True,
        requests_per_minute: float = 4.0,
        burst_capacity: int = 2,
        llm_call_logging_enabled: bool = False,
        llm_call_logging_redact: bool = True,
        llm_call_logging_max_field_chars: int = 256,
        llm_call_logging_include_chunks: bool = False,
        enable_thinking: bool = True,
    ):
        """Initialize the LLM service with optional rate limiting.

        Args:
            api_key: Provider API key. Required for Gemini, optional locally.
            model_name: Name of the LLM model to use
            api_keys: Optional ordered list of API keys for quota rotation
            provider: LLM provider: gemini, ollama, lmstudio, or openai_compatible
            base_url: Optional base URL for local/OpenAI-compatible providers
            rate_limit_enabled: Enable rate limiting (default: True)
            requests_per_minute: Max requests per minute (default: 4.0)
            burst_capacity: Max concurrent requests (default: 2)
            llm_call_logging_enabled: Enable detailed LLM payload logs
            llm_call_logging_redact: Redact sensitive payload fields when logging
            llm_call_logging_max_field_chars: Max chars retained per payload field
            llm_call_logging_include_chunks: Include per-chunk payload logging
            enable_thinking: Enable chain-of-thought for OpenAI-compatible providers
        """
        self.model_name = model_name
        if not self.model_name:
            raise ValueError("model_name must be provided")
        self.provider = provider.strip().lower()
        if self.provider not in SUPPORTED_LLM_PROVIDERS:
            supported = ", ".join(sorted(SUPPORTED_LLM_PROVIDERS))
            raise ValueError(
                f"Unsupported LLM provider: {provider}. Use one of: {supported}"
            )
        self.base_url = base_url
        configured_keys = [key for key in (api_keys or []) if key]
        if not configured_keys and api_key:
            configured_keys = [api_key]
        if not configured_keys and self.provider == "gemini":
            raise ValueError("At least one LLM API key must be configured")
        if not configured_keys:
            configured_keys = ["local"]

        self._api_keys = configured_keys
        self._active_key_index = 0
        self.api_key = self._api_keys[self._active_key_index]
        self.llm_call_logging_enabled = llm_call_logging_enabled
        self.llm_call_logging_redact = llm_call_logging_redact
        self.llm_call_logging_max_field_chars = max(
            64, llm_call_logging_max_field_chars
        )
        self.llm_call_logging_include_chunks = llm_call_logging_include_chunks
        self.enable_thinking = enable_thinking
        self._llm_call_logger = _get_llm_call_logger()
        self._llm_metrics_logger = logging.getLogger(LLM_METRICS_LOGGER_NAME)
        self.llm = self._build_llm_client(self.api_key)

        # Initialize rate limiter
        self.rate_limit_enabled = rate_limit_enabled
        if rate_limit_enabled:
            # Convert requests per minute to tokens per second
            tokens_per_second = requests_per_minute / 60.0
            self._rate_limiter = TrioRateLimiter(
                rate=tokens_per_second, capacity=float(burst_capacity)
            )
            logger.info(
                f"Rate limiting enabled: {requests_per_minute} req/min, "
                f"burst capacity: {burst_capacity}"
            )
        else:
            self._rate_limiter = None
            logger.info("Rate limiting disabled")

    def _chat_template_kwargs_for_provider(self) -> dict[str, Any] | None:
        if self.provider not in {"lmstudio", "openai_compatible"}:
            return None
        return {
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
        }

    def _build_llm_client(self, api_key: str) -> Any:
        if self.provider == "gemini":
            return ChatGoogleGenerativeAI(
                model=self.model_name, google_api_key=api_key, temperature=0.7
            )

        if self.provider == "ollama":
            if ChatOllama is None:
                raise ValueError(
                    "langchain-ollama must be installed for Ollama support"
                )
            kwargs: dict[str, Any] = {"model": self.model_name, "temperature": 0.7}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            return ChatOllama(**kwargs)

        if self.provider in {"lmstudio", "openai_compatible"}:
            if ChatOpenAI is None:
                raise ValueError(
                    "langchain-openai must be installed for OpenAI-compatible "
                    "provider support"
                )
            kwargs = {
                "model": self.model_name,
                "api_key": api_key if api_key != "local" else "not-needed",
                "temperature": 0.7,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            template_kwargs = self._chat_template_kwargs_for_provider()
            if template_kwargs:
                kwargs["extra_body"] = template_kwargs
            return ChatOpenAI(**kwargs)

        raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _is_quota_exhausted_error(self, error: Exception) -> bool:
        if ResourceExhausted is not None and isinstance(error, ResourceExhausted):
            return True
        type_name = type(error).__name__.lower()
        message = str(error).lower()
        return "resourceexhausted" in type_name or (
            "quota" in message and "exhaust" in message
        )

    def _rotate_to_next_key(self) -> bool:
        next_index = self._active_key_index + 1
        if next_index >= len(self._api_keys):
            return False
        self._active_key_index = next_index
        self.api_key = self._api_keys[next_index]
        self.llm = self._build_llm_client(self.api_key)
        logger.warning("Rotated LLM API key to index %s", self._active_key_index)
        return True

    def _invoke_with_key_rotation(self, messages: list[Any]) -> Any:
        for attempt in range(len(self._api_keys)):
            try:
                return self.llm.invoke(messages)
            except Exception as error:
                if not self._is_quota_exhausted_error(error):
                    raise
                is_last_attempt = attempt == len(self._api_keys) - 1
                if is_last_attempt or not self._rotate_to_next_key():
                    raise LLMQuotaExhaustedError(
                        "All configured LLM API keys are quota exhausted"
                    ) from error
        raise LLMQuotaExhaustedError("All configured LLM API keys are quota exhausted")

    def _trim_text(self, value: str) -> str:
        if len(value) <= self.llm_call_logging_max_field_chars:
            return value
        trimmed = value[: self.llm_call_logging_max_field_chars]
        remaining = len(value) - self.llm_call_logging_max_field_chars
        return f"{trimmed}...<truncated {remaining} chars>"

    def _redacted_text(self, value: str) -> str:
        return f"<redacted len={len(value)}>"

    def _sanitize_value(self, key: str, value: Any) -> Any:
        if isinstance(value, str):
            if self.llm_call_logging_redact and key in {
                "prompt",
                "response",
                "chunk",
                "template",
                "content",
            }:
                return self._redacted_text(value)
            return self._trim_text(value)

        if isinstance(value, dict):
            return {k: self._sanitize_value(k, v) for k, v in value.items()}

        if isinstance(value, list):
            if self.llm_call_logging_redact and key == "context":
                sanitized_context: list[Any] = []
                for item in value:
                    if isinstance(item, dict):
                        role = item.get("role", "unknown")
                        content = item.get("content", "")
                        if isinstance(content, str):
                            sanitized_context.append(
                                {
                                    "role": role,
                                    "content": self._redacted_text(content),
                                }
                            )
                        else:
                            sanitized_context.append(
                                {"role": role, "content": "<redacted>"}
                            )
                    else:
                        sanitized_context.append("<redacted>")
                return sanitized_context
            return [self._sanitize_value(key, item) for item in value]

        return value

    def _sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: self._sanitize_value(key, value) for key, value in payload.items()
        }

    @staticmethod
    def _build_langchain_messages(
        prompt: str, context: list[dict[str, str]] | None
    ) -> list[SystemMessage | HumanMessage | AIMessage]:
        messages: list[SystemMessage | HumanMessage | AIMessage] = []
        if context:
            for msg in context:
                role = msg.get("role")
                content = msg.get("content", "")
                if role == "system":
                    messages.append(SystemMessage(content=content))
                elif role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
        messages.append(HumanMessage(content=prompt))
        return messages

    def _log_llm_call(self, event: str, payload: dict[str, Any]) -> None:
        if not self.llm_call_logging_enabled:
            return
        if event == "stream_chunk" and not self.llm_call_logging_include_chunks:
            return

        record = {
            "event": event,
            "provider": self.provider,
            "model": self.model_name,
            **self._sanitize_payload(payload),
        }
        self._llm_call_logger.info(
            json.dumps(record, ensure_ascii=True, sort_keys=True, default=str)
        )

    def _log_metric(
        self,
        status: str,
        call_type: str,
        phase: str | None,
        *,
        started_at: float | None = None,
        response: Any = None,
    ) -> None:
        usage = getattr(response, "usage_metadata", None) or {}
        self._llm_metrics_logger.info(
            json.dumps(
                {
                    "phase": phase,
                    "call_type": call_type,
                    "provider": self.provider,
                    "model": self.model_name,
                    "latency_ms": (
                        round((time.perf_counter() - started_at) * 1000, 3)
                        if started_at is not None
                        else None
                    ),
                    "status": status,
                    "prompt_tokens": usage.get("input_tokens"),
                    "completion_tokens": usage.get("output_tokens"),
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )

    async def _acquire_rate_limit(self) -> None:
        """Acquire rate limit token if rate limiting is enabled."""
        if self.rate_limit_enabled and self._rate_limiter is not None:
            await self._rate_limiter.acquire()

    def generate_response(
        self,
        prompt: str,
        context: list[dict[str, str]] | None = None,
        *,
        phase: str | None = None,
    ) -> str:
        """
        Generate a response from the LLM.

        Args:
            prompt (str): The prompt to send to the LLM.
            context (Optional[List[Dict[str, str]]]): Optional conversation history.

        Returns:
            str: The LLM's response.
        """
        started_at = time.perf_counter()
        self._log_metric("start", "generate_response", phase)
        try:
            self._log_llm_call(
                "request",
                {
                    "call_type": "generate_response",
                    "prompt": prompt,
                    "context": context or [],
                },
            )
            if context:
                # Convert context to LangChain message format
                messages = []
                for msg in context:
                    if msg["role"] == "system":
                        messages.append(SystemMessage(content=msg["content"]))
                    elif msg["role"] == "user":
                        messages.append(HumanMessage(content=msg["content"]))
                    elif msg["role"] == "assistant":
                        messages.append(AIMessage(content=msg["content"]))

                # Add the current prompt
                messages.append(HumanMessage(content=prompt))

                # Generate response
                response = self._invoke_with_key_rotation(messages)
                logger.info(f"Generated LLM response for prompt: {prompt[:100]}...")
                self._log_llm_call(
                    "response",
                    {
                        "call_type": "generate_response",
                        "response": response.content,
                    },
                )
                self._log_metric(
                    "finish", "generate_response", phase, started_at=started_at, response=response
                )
                return response.content
            else:
                # Simple prompt without context
                response = self._invoke_with_key_rotation(
                    [HumanMessage(content=prompt)]
                )
                logger.info(
                    f"Generated LLM response for simple prompt: {prompt[:100]}..."
                )
                self._log_llm_call(
                    "response",
                    {
                        "call_type": "generate_response",
                        "response": response.content,
                    },
                )
                self._log_metric(
                    "finish", "generate_response", phase, started_at=started_at, response=response
                )
                return response.content
        except LLMQuotaExhaustedError:
            self._log_metric("failure", "generate_response", phase, started_at=started_at)
            raise
        except Exception as e:
            self._log_metric("failure", "generate_response", phase, started_at=started_at)
            import traceback

            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error generating LLM response: {e}", exc_info=True)
            # Re-raise the exception with full context instead of hiding it
            error_message = f"LLM generation failed: {type(e).__name__}: {str(e)}"
            raise LLMServiceError(
                f"{error_message}\n\nSTACKTRACE:\n{tb_str}"
            ) from e

    async def generate_response_stream(
        self, prompt: str, context: list[dict[str, str]] | None = None
    ) -> list[str]:
        """Compatibility helper that returns collected chunks."""
        chunks: list[str] = []
        async for chunk in self.stream_response(prompt, context):
            chunks.append(chunk)
        logger.info(
            "Streamed LLM response: %s chunks, %s chars",
            len(chunks),
            sum(len(c) for c in chunks),
        )
        return chunks

    async def stream_response(
        self,
        prompt: str,
        context: list[dict[str, str]] | None = None,
        *,
        phase: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream response chunks from the LLM in real time.

        This bridges LangChain's blocking stream iterator into Trio so callers can
        `async for` chunks and emit them as they arrive.
        """
        await self._acquire_rate_limit()

        started_at = time.perf_counter()
        self._log_metric("start", "stream_response", phase)
        try:
            self._log_llm_call(
                "request",
                {
                    "call_type": "stream_response",
                    "prompt": prompt,
                    "context": context or [],
                },
            )
            messages = self._build_langchain_messages(prompt, context)

            def _iterator():
                for chunk in self.llm.stream(messages):
                    chunk_text = getattr(chunk, "content", None)
                    if chunk_text:
                        yield chunk_text

            async for chunk in iter_in_thread(_iterator, buffer_size=3):
                self._log_llm_call(
                    "stream_chunk",
                    {
                        "call_type": "stream_response",
                        "chunk": chunk,
                    },
                )
                yield chunk
            self._log_metric("finish", "stream_response", phase, started_at=started_at)

        except Exception as e:
            self._log_metric("failure", "stream_response", phase, started_at=started_at)
            import traceback

            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error streaming LLM response: {e}", exc_info=True)
            error_message = f"LLM streaming failed: {type(e).__name__}: {str(e)}"
            raise LLMServiceError(
                f"{error_message}\n\nSTACKTRACE:\n{tb_str}"
            ) from e

    def generate_structured_output(
        self,
        prompt: str,
        schema: dict | type[BaseModel],
        *,
        method: str = "json_schema",
        phase: str | None = None,
    ) -> Any:
        """Generate a structured output and normalize it to the requested schema."""
        started_at = time.perf_counter()
        self._log_metric("start", "generate_structured_output", phase)
        try:
            if self.provider != "gemini":
                response = self._generate_structured_output_from_json_prompt(prompt, schema)
                self._log_metric(
                    "finish", "generate_structured_output", phase, started_at=started_at
                )
                return response

            schema_payload: dict[str, Any]
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                schema_payload = {"model": schema.__name__}
                self._log_llm_call(
                    "request",
                    {
                        "call_type": "generate_structured_output",
                        "prompt": prompt,
                        "schema": schema_payload,
                    },
                )
                runnable = self.llm.with_structured_output(schema, method=method)
                response = runnable.invoke(prompt)
                self._log_llm_call(
                    "response",
                    {
                        "call_type": "generate_structured_output",
                        "response": response,
                    },
                )
                self._log_metric(
                    "finish", "generate_structured_output", phase, started_at=started_at, response=response
                )
                return response

            schema_payload = {"schema": schema}
            self._log_llm_call(
                "request",
                {
                    "call_type": "generate_structured_output",
                    "prompt": prompt,
                    "schema": schema_payload,
                },
            )
            runnable = self.llm.with_structured_output(schema, method=method)
            response = runnable.invoke(prompt)
            self._log_llm_call(
                "response",
                {
                    "call_type": "generate_structured_output",
                    "response": response,
                },
            )
            self._log_metric(
                "finish", "generate_structured_output", phase, started_at=started_at, response=response
            )
            return response
        except Exception:
            self._log_metric(
                "failure", "generate_structured_output", phase, started_at=started_at
            )
            raise

    def _generate_structured_output_from_json_prompt(
        self,
        prompt: str,
        schema: dict | type[BaseModel],
    ) -> Any:
        """Use prompt-constrained JSON for providers without native schema support."""
        schema_payload: dict[str, Any]
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            schema_payload = schema.model_json_schema()
        else:
            schema_payload = schema

        structured_prompt = (
            f"{prompt}\n\n"
            "Return only valid JSON that conforms to this JSON Schema. "
            "Do not include markdown fences, commentary, or extra text.\n\n"
            f"JSON Schema:\n{json.dumps(schema_payload, ensure_ascii=True)}"
        )
        self._log_llm_call(
            "request",
            {
                "call_type": "generate_structured_output",
                "prompt": structured_prompt,
                "schema": schema_payload,
            },
        )
        response = self._invoke_with_key_rotation(
            [HumanMessage(content=structured_prompt)]
        )
        content = getattr(response, "content", response)
        if not isinstance(content, str):
            content = str(content)
        content = self._strip_json_markdown(content)

        try:
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                parsed = schema.model_validate_json(content)
            else:
                parsed = json.loads(content)
        except Exception as error:
            raise LLMServiceError(
                "LLM structured output parsing failed: "
                f"{type(error).__name__}: {error}"
            ) from error

        self._log_llm_call(
            "response",
            {
                "call_type": "generate_structured_output",
                "response": parsed,
            },
        )
        return parsed

    @staticmethod
    def _strip_json_markdown(content: str) -> str:
        stripped = content.strip()
        if not stripped.startswith("```"):
            return stripped
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    async def generate_response_async(
        self,
        prompt: str,
        context: list[dict[str, str]] | None = None,
        *,
        phase: str | None = None,
    ) -> str:
        """Generate a response from the LLM asynchronously with rate limiting.

        Args:
            prompt: The prompt to send to the LLM
            context: Optional conversation history

        Returns:
            str: The LLM's response
        """
        # Apply rate limiting before starting the request
        await self._acquire_rate_limit()

        if phase is None:
            return await trio.to_thread.run_sync(self.generate_response, prompt, context)
        return await trio.to_thread.run_sync(
            lambda: self.generate_response(prompt, context, phase=phase)
        )

    async def generate_structured_output_async(
        self,
        prompt: str,
        schema: dict | type[BaseModel],
        *,
        method: str = "json_schema",
        phase: str | None = None,
    ) -> Any:
        """Async wrapper for generate_structured_output with rate limiting."""
        await self._acquire_rate_limit()
        # trio.to_thread.run_sync doesn't forward arbitrary kwargs to the target
        # callable, so pass keyword-only args via a closure.
        if phase is None:
            return await trio.to_thread.run_sync(
                lambda: self.generate_structured_output(prompt, schema, method=method)
            )
        return await trio.to_thread.run_sync(
            lambda: self.generate_structured_output(
                prompt, schema, method=method, phase=phase
            )
        )
