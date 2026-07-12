"""Structured contract strictness tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jung.phases.intake.models import IntakeRecordPatch


def test_intake_patch_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        IntakeRecordPatch.model_validate({"unexpected_field": "value"})
