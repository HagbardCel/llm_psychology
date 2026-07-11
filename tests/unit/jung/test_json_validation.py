"""Unit tests for strict JSON document validation."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.domain.errors import InvariantViolation
from jung.persistence import _sqlite_support as sql


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("text", "must be a mapping"),
        ({1: "x"}, "keys must be strings"),
        ({"a": {1: 2}}, "keys must be strings"),
        ({"a": uuid4()}, "JSON-compatible"),
        ({"x": float("nan")}, "finite numbers"),
        ({"a": (1,)}, "JSON-compatible"),
    ],
)
def test_validate_json_mapping_rejects_malformed_values(
    value: object, match: str
) -> None:
    with pytest.raises(InvariantViolation, match=match):
        sql.validate_json_mapping(value, field_name="result")


def test_validate_json_mapping_rejects_circular_reference() -> None:
    payload: dict[str, object] = {}
    payload["self"] = payload
    with pytest.raises(InvariantViolation, match="circular reference"):
        sql.validate_json_mapping(payload, field_name="result")


def test_validate_json_mapping_accepts_valid_mapping() -> None:
    validated = sql.validate_json_mapping(
        {"a": [1, {"b": "ok"}], "c": None},
        field_name="result",
    )
    assert validated == {"a": [1, {"b": "ok"}], "c": None}
