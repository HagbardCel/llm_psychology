"""Durable grounded patient-turn records and strict profile parsing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jung.domain.text import normalize_content

_GROUNDED_TURNS_KEY = "grounded_patient_turns"


class GroundedPatientTurn(BaseModel):
    """Authoritative full patient turn retained in the derived profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_message_id: UUID
    source_sequence: int = Field(ge=1)
    content: str

    @field_validator("content")
    @classmethod
    def normalize_non_empty_content(cls, value: str) -> str:
        value = normalize_content(value)
        if not value:
            raise ValueError("content must be non-empty")
        return value


def parse_grounded_patient_turns(
    profile: Mapping[str, Any],
) -> tuple[GroundedPatientTurn, ...]:
    """Strictly parse stored grounded patient turns from a profile mapping.

    Missing key yields an empty tuple. A present key that is not a list
    (including explicit ``null``) raises ``ValueError``. Duplicate
    ``source_message_id`` values are rejected.
    """
    if _GROUNDED_TURNS_KEY not in profile:
        return ()
    value = profile[_GROUNDED_TURNS_KEY]
    if not isinstance(value, list):
        raise ValueError("grounded_patient_turns must be a list")
    turns = tuple(GroundedPatientTurn.model_validate(item) for item in value)
    seen: set[UUID] = set()
    for turn in turns:
        if turn.source_message_id in seen:
            raise ValueError(
                f"duplicate grounded patient source message: {turn.source_message_id}"
            )
        seen.add(turn.source_message_id)
    return turns
