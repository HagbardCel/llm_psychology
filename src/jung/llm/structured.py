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

_STRUCTURAL_SCHEMA_KEYS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "$defs",
        "$ref",
        "anyOf",
        "enum",
        "description",
    }
)

_CONSTRAINT_SCHEMA_KEYS = frozenset(
    {
        "pattern",
        "format",
        "minLength",
        "maxLength",
        "multipleOf",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minItems",
        "maxItems",
        "const",
    }
)

_STRIPPED_SCHEMA_KEYS = frozenset({"default", "title"})

_ALLOWED_SCHEMA_KEYS = _STRUCTURAL_SCHEMA_KEYS | _CONSTRAINT_SCHEMA_KEYS


class UnsupportedStrictSchema(ValueError):
    """Raised when a model schema cannot be converted to the strict subset."""


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


def _reject_unknown_schema_keys(
    node: dict[str, Any],
    *,
    path: str,
    reject_stripped_metadata: bool = False,
) -> None:
    for key in node:
        if key in _STRIPPED_SCHEMA_KEYS:
            if reject_stripped_metadata:
                raise UnsupportedStrictSchema(
                    f"stripped schema metadata {key!r} must not remain "
                    f"at {path or 'root'}"
                )
            continue
        if key not in _ALLOWED_SCHEMA_KEYS:
            raise UnsupportedStrictSchema(
                f"unsupported schema keyword {key!r} at {path or 'root'}"
            )


def to_provider_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Narrow a JSON schema dict to the OpenAI strict json_schema subset."""

    if "anyOf" in schema:
        raise UnsupportedStrictSchema("root-level anyOf is not supported")
    if schema.get("type") != "object":
        raise UnsupportedStrictSchema("root schema must be type object")

    def transform(node: Any, *, path: str) -> Any:
        if not isinstance(node, dict):
            return node
        _reject_unknown_schema_keys(node, path=path)
        result = {
            key: value
            for key, value in node.items()
            if key not in _STRIPPED_SCHEMA_KEYS
        }
        node_type = result.get("type")
        if node_type == "object":
            properties = result.get("properties")
            if isinstance(properties, dict):
                result["properties"] = {
                    key: transform(value, path=f"{path}.properties.{key}")
                    for key, value in properties.items()
                }
                result["required"] = sorted(properties.keys())
            result["additionalProperties"] = False
        elif node_type == "array":
            items = result.get("items")
            if isinstance(items, dict):
                result["items"] = transform(items, path=f"{path}.items")
        defs = result.get("$defs")
        if isinstance(defs, dict):
            result["$defs"] = {
                key: transform(value, path=f"{path}.$defs.{key}")
                for key, value in defs.items()
            }
        any_of = result.get("anyOf")
        if isinstance(any_of, list):
            result["anyOf"] = [
                transform(branch, path=f"{path}.anyOf[{index}]")
                for index, branch in enumerate(any_of)
            ]
        return result

    return transform(schema, path="root")


def assert_valid_strict_provider_schema(schema: dict[str, Any]) -> None:
    """Validate a provider payload schema against the strict subset rules."""

    def walk(node: Any, *, path: str, is_root: bool) -> None:
        if not isinstance(node, dict):
            return
        if is_root:
            if node.get("type") != "object":
                raise AssertionError("root schema must be type object")
            if "anyOf" in node:
                raise AssertionError("root schema must not contain anyOf")
        _reject_unknown_schema_keys(
            node,
            path=path,
            reject_stripped_metadata=True,
        )
        if node.get("type") == "object":
            properties = node.get("properties")
            if not isinstance(properties, dict):
                raise AssertionError(f"object at {path} must define properties")
            required = node.get("required")
            if required != sorted(properties.keys()):
                raise AssertionError(f"object at {path} must require all properties")
            if node.get("additionalProperties") is not False:
                raise AssertionError(
                    f"object at {path} must set additionalProperties false"
                )
            for key, value in properties.items():
                walk(value, path=f"{path}.properties.{key}", is_root=False)
        if node.get("type") == "array":
            items = node.get("items")
            if isinstance(items, dict):
                walk(items, path=f"{path}.items", is_root=False)
        defs = node.get("$defs")
        if isinstance(defs, dict):
            for key, value in defs.items():
                walk(value, path=f"{path}.$defs.{key}", is_root=False)
        any_of = node.get("anyOf")
        if isinstance(any_of, list):
            for index, branch in enumerate(any_of):
                walk(branch, path=f"{path}.anyOf[{index}]", is_root=False)

    walk(schema, path="root", is_root=True)


def response_format_for_mode(
    mode: StructuredOutputMode,
    output_type: type[BaseModel],
) -> dict[str, object] | None:
    if mode is StructuredOutputMode.JSON_SCHEMA:
        schema = to_provider_strict_json_schema(output_type.model_json_schema())
        assert_valid_strict_provider_schema(schema)
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
