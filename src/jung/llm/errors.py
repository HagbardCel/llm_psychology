"""LLM infrastructure-boundary errors."""

from __future__ import annotations

from typing import ClassVar


class LLMError(Exception):
    code: ClassVar[str]

    def __init__(self, message: str, *, retryable: bool) -> None:
        self.retryable = retryable
        super().__init__(message)


class LLMUnavailable(LLMError):
    code = "llm_unavailable"


class LLMTimeout(LLMError):
    code = "llm_timeout"


class InvalidLLMOutput(LLMError):
    code = "invalid_llm_output"


class LLMProtocolError(LLMError):
    code = "internal_error"
