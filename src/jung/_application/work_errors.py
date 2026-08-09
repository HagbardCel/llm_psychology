"""Public error classification for chat and durable operation failures."""

from __future__ import annotations

from jung.llm.errors import LLMError

_PUBLIC_WORK_ERROR_MESSAGES = {
    "llm_unavailable": "The language model is currently unavailable.",
    "llm_timeout": "The language model request timed out.",
    "invalid_llm_output": "The language model returned an invalid response.",
    "internal_error": "An unexpected error occurred.",
}


def _classify_work_error(exc: Exception) -> tuple[str, str, bool]:
    if isinstance(exc, LLMError):
        return (
            exc.code,
            _PUBLIC_WORK_ERROR_MESSAGES.get(
                exc.code,
                "The language model request failed.",
            ),
            exc.retryable,
        )
    return "internal_error", "An unexpected error occurred.", False
