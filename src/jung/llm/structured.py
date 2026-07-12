"""Structured output normalization and validation helpers."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from jung.llm.errors import InvalidLLMOutput
from jung.llm.gateway import ChatMessage, ChatRole, StructuredOutputMode

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def strip_markdown_json_fence(text: str) -> str:
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors()[:5]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        message = error.get("msg", "invalid")
        parts.append(f"{location}: {message}")
    return "; ".join(parts) if parts else str(exc)


def validate_structured_text(output_type: type[T], text: str) -> T:
    normalized = strip_markdown_json_fence(text)
    try:
        return output_type.model_validate_json(normalized)
    except ValidationError as exc:
        raise InvalidLLMOutput(
            format_validation_error(exc), retryable=False
        ) from exc


def build_prompt_schema_instruction(output_type: type[BaseModel]) -> str:
    schema = json.dumps(output_type.model_json_schema(), indent=2, sort_keys=True)
    return (
        "Respond with JSON only that matches this schema. "
        "Do not include markdown or commentary.\n"
        f"{schema}"
    )


def build_correction_messages(
    *,
    original_messages: list[ChatMessage],
    output_type: type[BaseModel],
    invalid_text: str,
    validation_message: str,
) -> list[ChatMessage]:
    bounded_invalid = invalid_text[:4000]
    correction = ChatMessage(
        role=ChatRole.USER,
        content=(
            f"The previous response for {output_type.__name__} was invalid: "
            f"{validation_message}. Invalid response:\n{bounded_invalid}\n"
            "Return only corrected JSON."
        ),
    )
    return [*original_messages, correction]


def response_format_for_mode(
    mode: StructuredOutputMode,
    output_type: type[BaseModel],
) -> dict[str, object] | None:
    if mode is StructuredOutputMode.JSON_SCHEMA:
        schema = output_type.model_json_schema()
        return {
            "type": "json_schema",
            "json_schema": {
                "name": output_type.__name__,
                "schema": schema,
                "strict": True,
            },
        }
    if mode is StructuredOutputMode.JSON_OBJECT:
        return {"type": "json_object"}
    return None
