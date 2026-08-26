"""Regression coverage for intake extraction ownership (#72)."""

from __future__ import annotations

from uuid import uuid4

from jung.llm.gateway import StructuredOutputMode
from jung.llm.structured import response_format_for_mode, validate_structured_text
from jung.phases.intake.extraction import (
    IntakeEvidenceField,
    IntakeExtraction,
    materialize_extraction,
)
from jung.phases.transcript import TranscriptTurn

_FORBIDDEN_SCHEMA_PROPERTIES = frozenset(
    {
        "direct_ask",
        "source_role",
        "source_message_sequence",
        "no_new_information",
        "rationale",
    }
)


def _collect_property_names(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            found.update(properties)
            for child in properties.values():
                _collect_property_names(child, found)
        for key, value in node.items():
            if key != "properties":
                _collect_property_names(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_property_names(item, found)


def test_intake_extraction_provider_schema_omits_jung_owned_fields() -> None:
    payload = response_format_for_mode(
        StructuredOutputMode.JSON_SCHEMA,
        IntakeExtraction,
    )
    assert payload is not None
    schema = payload["json_schema"]["schema"]
    assert isinstance(schema, dict)
    names: set[str] = set()
    _collect_property_names(schema, names)
    assert names.isdisjoint(_FORBIDDEN_SCHEMA_PROPERTIES)


def test_issue_72_flat_unknown_payload_parses_and_materializes() -> None:
    """#72-shaped flat payload: unknown without model-owned direct_ask."""
    raw = (
        '{"evidence":[{"field":"presenting_problem.main_concern",'
        '"evidence_quote":"I\'m not sure",'
        '"response_status":"unknown","confidence":"medium"}]}'
    )
    extraction = validate_structured_text(IntakeExtraction, raw)
    assert len(extraction.evidence) == 1
    assert (
        extraction.evidence[0].field
        is IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN
    )
    turn = TranscriptTurn(
        message_id=uuid4(),
        sequence=1,
        role="user",
        content="I'm not sure",
    )
    result = materialize_extraction(
        extraction,
        latest_user_turn=turn,
        prompted_item="presenting_problem",
    )
    assert result.materialized_candidate_count == 1
    evidence = result.patch.presenting_problem.main_concern  # type: ignore[union-attr]
    assert evidence.response_status == "unknown"
    assert evidence.direct_ask is True
    assert evidence.source_role == "user"
    assert evidence.source_message_sequence == 1
