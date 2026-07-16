"""Package-private environment parsing helpers."""

from __future__ import annotations

import json
import math

_TRUE_VALUES = frozenset({"1", "true", "yes"})
_FALSE_VALUES = frozenset({"0", "false", "no"})


def _reject_json_constant(value: str) -> None:
    raise ValueError("invalid JSON constant")


def parse_bool(name: str, raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    if not raw.strip():
        raise ValueError(f"{name} must be one of 1/true/yes or 0/false/no")
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be one of 1/true/yes or 0/false/no")


def parse_positive_finite_float(name: str, raw: str | None, *, default: float) -> float:
    if raw is None:
        return default
    if not raw.strip():
        raise ValueError(f"{name} must be a finite positive number")
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def parse_positive_int(name: str, raw: str | None, *, default: int) -> int:
    if raw is None:
        return default
    if not raw.strip():
        raise ValueError(f"{name} must be a positive integer")
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def require_non_empty_string(name: str, raw: str | None, *, default: str) -> str:
    if raw is None:
        value = default
    elif not raw.strip():
        raise ValueError(f"{name} must be non-empty")
    else:
        value = raw.strip()
    if not value:
        raise ValueError(f"{name} must be non-empty")
    return value


def optional_string(raw: str | None, *, default: str = "") -> str:
    if raw is None:
        return default
    return raw


def assert_finite_json_numbers(value: object, *, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} must be a finite number")
    if isinstance(value, dict):
        for key, item in value.items():
            assert_finite_json_numbers(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_finite_json_numbers(item, path=f"{path}[{index}]")


def parse_optional_json_object(name: str, raw: str | None) -> dict[str, object] | None:
    if raw is None or not raw.strip():
        return None
    try:
        parsed = json.loads(
            raw,
            parse_constant=_reject_json_constant,
        )
    except ValueError as exc:
        raise ValueError(f"{name} must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object")
    assert_finite_json_numbers(parsed, path=name)
    return parsed
