"""Unit tests for application snapshot and worker-error invariants."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.application import (
    _classify_worker_error,
    _validate_snapshot_invariants,
)
from jung.domain.errors import InvariantViolation
from jung.domain.models import (
    AppSnapshot,
    CommandName,
    Plan,
    Stage,
)
from jung.llm.errors import (
    InvalidLLMOutput,
    LLMProtocolError,
    LLMTimeout,
    LLMUnavailable,
)
from jung.styles import load_styles


def test_validate_snapshot_invariants_rejects_unknown_plan_style() -> None:
    now = datetime.now(UTC)
    plan = Plan(
        id=uuid4(),
        version=1,
        selected_style="unknown-style",
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=[],
        created_at=now,
    )
    snapshot = AppSnapshot(
        stage=Stage.READY,
        profile_complete=True,
        selected_style="unknown-style",
        available_commands=frozenset({CommandName.START_SESSION}),
    )
    with pytest.raises(InvariantViolation, match="unknown style"):
        _validate_snapshot_invariants(snapshot, plan, load_styles())


def test_validate_snapshot_invariants_rejects_therapy_without_session() -> None:
    snapshot = AppSnapshot(
        stage=Stage.THERAPY,
        profile_complete=True,
        available_commands=frozenset(
            {CommandName.SEND_MESSAGE, CommandName.END_SESSION}
        ),
    )
    with pytest.raises(
        InvariantViolation, match="THERAPY requires an open therapy session"
    ):
        _validate_snapshot_invariants(snapshot, None, load_styles())


SECRET_MARKER = "secret-marker https://api.example.com sk-test-key"


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_message", "expected_retryable"),
    [
        (
            LLMUnavailable(SECRET_MARKER),
            "llm_unavailable",
            "The language model is currently unavailable.",
            True,
        ),
        (
            LLMTimeout(SECRET_MARKER),
            "llm_timeout",
            "The language model request timed out.",
            True,
        ),
        (
            InvalidLLMOutput(SECRET_MARKER),
            "invalid_llm_output",
            "The language model returned an invalid response.",
            False,
        ),
        (
            LLMProtocolError(SECRET_MARKER),
            "internal_error",
            "An unexpected error occurred.",
            False,
        ),
    ],
)
def test_classify_worker_error_maps_llm_errors_to_public_messages(
    error: Exception,
    expected_code: str,
    expected_message: str,
    expected_retryable: bool,
) -> None:
    code, message, retryable = _classify_worker_error(error)
    assert code == expected_code
    assert message == expected_message
    assert retryable is expected_retryable
    assert SECRET_MARKER not in message


def test_classify_worker_error_maps_unexpected_errors() -> None:
    code, message, retryable = _classify_worker_error(RuntimeError("boom"))
    assert code == "internal_error"
    assert message == "An unexpected error occurred."
    assert retryable is False
    assert "boom" not in message
