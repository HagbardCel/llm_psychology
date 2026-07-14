"""Tests for structured output helpers."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from jung.llm.errors import InvalidLLMOutput
from jung.llm.gateway import StructuredOutputMode
from jung.llm.structured import (
    UnsupportedStrictSchema,
    assert_valid_strict_provider_schema,
    response_format_for_mode,
    strip_markdown_json_fence,
    to_provider_strict_json_schema,
    validate_structured_text,
)
from jung.phases.assessment.models import AssessmentResult
from jung.phases.intake.models import IntakeRecordPatch
from jung.phases.post_session.models import PostSessionResult, SessionAnalysisResult


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
    assert_valid_strict_provider_schema(schema)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["name"]
    assert "title" not in schema
    assert "default" not in schema


def test_response_format_uses_strict_provider_schema() -> None:
    payload = response_format_for_mode(StructuredOutputMode.JSON_SCHEMA, _Sample)
    assert payload is not None
    json_schema = payload["json_schema"]
    assert isinstance(json_schema, dict)
    inner = json_schema["schema"]
    assert isinstance(inner, dict)
    assert_valid_strict_provider_schema(inner)


@pytest.mark.parametrize(
    "output_type",
    [
        IntakeRecordPatch,
        AssessmentResult,
        SessionAnalysisResult,
        PostSessionResult,
    ],
)
def test_real_output_models_produce_valid_strict_provider_payload(
    output_type: type[BaseModel],
) -> None:
    payload = response_format_for_mode(StructuredOutputMode.JSON_SCHEMA, output_type)
    assert payload is not None
    inner = payload["json_schema"]["schema"]
    assert isinstance(inner, dict)
    assert_valid_strict_provider_schema(inner)


@pytest.mark.parametrize("metadata_key", ["title", "default"])
def test_strict_provider_schema_rejects_stripped_metadata(
    metadata_key: str,
) -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
        metadata_key: "unexpected",
    }
    with pytest.raises(UnsupportedStrictSchema, match=metadata_key):
        assert_valid_strict_provider_schema(schema)


def test_root_anyof_is_rejected() -> None:
    with pytest.raises(UnsupportedStrictSchema, match="root-level anyOf"):
        to_provider_strict_json_schema({"anyOf": [{"type": "object"}]})


def test_allof_is_rejected() -> None:
    with pytest.raises(UnsupportedStrictSchema, match="allOf"):
        to_provider_strict_json_schema(
            {
                "type": "object",
                "properties": {"value": {"allOf": [{"type": "string"}]}},
            }
        )


def test_unknown_schema_keyword_is_rejected() -> None:
    with pytest.raises(UnsupportedStrictSchema, match="examples"):
        to_provider_strict_json_schema(
            {
                "type": "object",
                "properties": {"value": {"type": "string", "examples": ["x"]}},
            }
        )
