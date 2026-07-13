"""Tests for structured output helpers."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from jung.llm.errors import InvalidLLMOutput
from jung.llm.gateway import StructuredOutputMode
from jung.llm.structured import (
    response_format_for_mode,
    strip_markdown_json_fence,
    to_provider_strict_json_schema,
    validate_structured_text,
)


class _Sample(BaseModel):
    name: str


def test_strip_markdown_json_fence() -> None:
    assert strip_markdown_json_fence('```json\n{"name":"x"}\n```') == '{"name":"x"}'


def test_validate_structured_text_success() -> None:
    result = validate_structured_text(_Sample, '{"name":"alex"}')
    assert result.name == "alex"


def test_validate_structured_text_raises_invalid_llm_output() -> None:
    with pytest.raises(InvalidLLMOutput):
        validate_structured_text(_Sample, '{"name": 1}')


def test_to_provider_strict_json_schema_marks_objects_strict() -> None:
    schema = to_provider_strict_json_schema(_Sample.model_json_schema())
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["name"]


def test_response_format_uses_strict_provider_schema() -> None:
    payload = response_format_for_mode(StructuredOutputMode.JSON_SCHEMA, _Sample)
    assert payload is not None
    json_schema = payload["json_schema"]
    assert isinstance(json_schema, dict)
    inner = json_schema["schema"]
    assert isinstance(inner, dict)
    assert inner["additionalProperties"] is False
    assert inner["required"] == ["name"]
