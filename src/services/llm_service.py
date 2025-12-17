import logging
from typing import Any

import trio
from langchain_classic.chains import LLMChain
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from exceptions import LLMServiceError

logger = logging.getLogger(__name__)


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
        # Initialized lazily in `acquire()` (cannot call `trio.current_time()` outside async context).
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
        api_key: str,
        model_name: str,
        rate_limit_enabled: bool = True,
        requests_per_minute: float = 4.0,
        burst_capacity: int = 2,
    ):
        """Initialize the LLM service with optional rate limiting.

        Args:
            api_key: Google Gemini API key
            model_name: Name of the LLM model to use
            rate_limit_enabled: Enable rate limiting (default: True)
            requests_per_minute: Max requests per minute (default: 4.0)
            burst_capacity: Max concurrent requests (default: 2)
        """
        self.api_key = api_key
        self.model_name = model_name
        self.llm = ChatGoogleGenerativeAI(
            model=model_name, google_api_key=api_key, temperature=0.7
        )

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

    async def _acquire_rate_limit(self) -> None:
        """Acquire rate limit token if rate limiting is enabled."""
        if self.rate_limit_enabled and self._rate_limiter is not None:
            await self._rate_limiter.acquire()

    def generate_response(
        self, prompt: str, context: list[dict[str, str]] | None = None
    ) -> str:
        """
        Generate a response from the LLM.

        Args:
            prompt (str): The prompt to send to the LLM.
            context (Optional[List[Dict[str, str]]]): Optional conversation history.

        Returns:
            str: The LLM's response.
        """
        try:
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
                response = self.llm.invoke(messages)
                logger.info(f"Generated LLM response for prompt: {prompt[:100]}...")
                return response.content
            else:
                # Simple prompt without context
                response = self.llm.invoke([HumanMessage(content=prompt)])
                logger.info(
                    f"Generated LLM response for simple prompt: {prompt[:100]}..."
                )
                return response.content
        except Exception as e:
            import traceback

            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error generating LLM response: {e}", exc_info=True)
            # Re-raise the exception with full context instead of hiding it
            raise LLMServiceError(
                f"LLM generation failed: {type(e).__name__}: {str(e)}\n\nSTACKTRACE:\n{tb_str}"
            ) from e

    async def generate_response_stream(
        self, prompt: str, context: list[dict[str, str]] | None = None
    ) -> list[str]:
        """Generate a streaming response from the LLM with rate limiting.

        This method runs LangChain's streaming in a thread pool and collects
        all chunks. The caller can then yield them in async context.
        Rate limiting is applied before starting the stream.

        Args:
            prompt: The prompt to send to the LLM
            context: Optional conversation history

        Returns:
            List[str]: List of response chunks in order
        """
        # Apply rate limiting before starting the request
        await self._acquire_rate_limit()

        try:
            # Build messages
            messages = []
            if context:
                for msg in context:
                    if msg["role"] == "system":
                        messages.append(SystemMessage(content=msg["content"]))
                    elif msg["role"] == "user":
                        messages.append(HumanMessage(content=msg["content"]))
                    elif msg["role"] == "assistant":
                        messages.append(AIMessage(content=msg["content"]))

            messages.append(HumanMessage(content=prompt))

            # Run LLM streaming in a thread - collect all chunks
            def _stream_blocking():
                chunks = []
                for chunk in self.llm.stream(messages):
                    chunk_text = chunk.content
                    if chunk_text:
                        chunks.append(chunk_text)
                return chunks

            # Execute in thread pool and get all chunks
            chunks = await trio.to_thread.run_sync(_stream_blocking)

            logger.info(
                f"Streamed LLM response: {len(chunks)} chunks, {sum(len(c) for c in chunks)} chars"
            )
            return chunks

        except Exception as e:
            import traceback

            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error streaming LLM response: {e}", exc_info=True)
            raise LLMServiceError(
                f"LLM streaming failed: {type(e).__name__}: {str(e)}\n\nSTACKTRACE:\n{tb_str}"
            ) from e

    def generate_structured_output(
        self,
        prompt: str,
        schema: dict | type["BaseModel"],
        *,
        method: str = "json_schema",
    ) -> Any:
        """
        Generate a structured output using Gemini's native structured output support.

        This avoids JSON scraping/parsing by relying on `response_mime_type` +
        schema-guided decoding inside the Gemini API / LangChain integration.
        """
        # Import here to avoid hard dependency in module import order.
        from pydantic import BaseModel

        if isinstance(schema, type) and issubclass(schema, BaseModel):
            runnable = self.llm.with_structured_output(schema, method=method)
            return runnable.invoke(prompt)

        runnable = self.llm.with_structured_output(schema, method=method)
        return runnable.invoke(prompt)

    def create_prompt_template(
        self, template: str, input_variables: list[str]
    ) -> PromptTemplate:
        """
        Create a prompt template for reusable prompts.

        Args:
            template (str): The template string with placeholders.
            input_variables (List[str]): List of variable names in the template.

        Returns:
            PromptTemplate: The created prompt template.
        """
        return PromptTemplate(template=template, input_variables=input_variables)

    def run_prompt_chain(
        self, prompt_template: PromptTemplate, inputs: dict[str, Any]
    ) -> str:
        """
        Run a prompt chain using a template and inputs.

        Args:
            prompt_template (PromptTemplate): The prompt template to use.
            inputs (Dict[str, Any]): The input values for the template.

        Returns:
            str: The LLM's response.
        """
        try:
            chain = LLMChain(llm=self.llm, prompt=prompt_template)
            response = chain.run(**inputs)
            return response
        except Exception as e:
            import traceback

            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error running prompt chain: {e}", exc_info=True)
            # Re-raise with full stacktrace
            raise LLMServiceError(
                f"Prompt chain failed: {type(e).__name__}: {str(e)}\n\nSTACKTRACE:\n{tb_str}"
            ) from e

    async def generate_response_async(
        self, prompt: str, context: list[dict[str, str]] | None = None
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

        return await trio.to_thread.run_sync(self.generate_response, prompt, context)

    async def generate_structured_output_async(
        self,
        prompt: str,
        schema: dict | type["BaseModel"],
        *,
        method: str = "json_schema",
    ) -> Any:
        """Async wrapper for generate_structured_output with rate limiting."""
        await self._acquire_rate_limit()
        # trio.to_thread.run_sync doesn't forward arbitrary kwargs to the target callable,
        # so pass keyword-only args via a closure.
        return await trio.to_thread.run_sync(
            lambda: self.generate_structured_output(prompt, schema, method=method)
        )
