"""LLM infrastructure-boundary errors."""

from __future__ import annotations

from typing import ClassVar


class LLMError(Exception):
    code: ClassVar[str]
    retryable: ClassVar[bool]

    def __init__(self, message: str) -> None:
        super().__init__(message)


class LLMUnavailable(LLMError):
    code = "llm_unavailable"
    retryable = True


class LLMTimeout(LLMError):
    code = "llm_timeout"
    retryable = True


class InvalidLLMOutput(LLMError):
    code = "invalid_llm_output"
    retryable = False


class LLMProtocolError(LLMError):
    code = "internal_error"
    retryable = False
