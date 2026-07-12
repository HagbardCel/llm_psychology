"""Tests for structured output helpers."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from jung.llm.errors import InvalidLLMOutput
from jung.llm.structured import (
    strip_markdown_json_fence,
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
