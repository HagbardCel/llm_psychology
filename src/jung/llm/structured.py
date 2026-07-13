"""Structured output normalization and validation helpers."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

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


def format_semantic_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return format_validation_error(exc)
    return str(exc)


def validate_structured_text(output_type: type[T], text: str) -> T:
    normalized = strip_markdown_json_fence(text)
    try:
        return output_type.model_validate_json(normalized)
    except ValidationError as exc:
        raise InvalidLLMOutput(format_validation_error(exc)) from exc


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


def to_provider_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Narrow a JSON schema dict to the OpenAI strict json_schema subset."""

    def transform(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        result = dict(node)
        node_type = result.get("type")
        if node_type == "object":
            properties = result.get("properties")
            if isinstance(properties, dict):
                result["properties"] = {
                    key: transform(value) for key, value in properties.items()
                }
                result["required"] = sorted(properties.keys())
            result["additionalProperties"] = False
        elif node_type == "array":
            items = result.get("items")
            if isinstance(items, dict):
                result["items"] = transform(items)
        defs = result.get("$defs")
        if isinstance(defs, dict):
            result["$defs"] = {
                key: transform(value) for key, value in defs.items()
            }
        return result

    return transform(schema)


def response_format_for_mode(
    mode: StructuredOutputMode,
    output_type: type[BaseModel],
) -> dict[str, object] | None:
    if mode is StructuredOutputMode.JSON_SCHEMA:
        schema = to_provider_strict_json_schema(output_type.model_json_schema())
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
