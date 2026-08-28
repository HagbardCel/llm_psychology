"""Category C clear-risk-denial evidence helpers (eval-local only)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from evals.simulation.intake_forensics import iter_record_evidence_paths
from jung.diagnostics import (
    current_diagnostic_context,
    open_private_file,
    sanitize_value,
)
from jung.domain.text import normalize_content
from jung.llm.gateway import LLMTask, StructuredOutputMode
from jung.llm.structured import (
    build_prompt_schema_instruction,
    response_format_for_mode,
)
from jung.phases.intake.extraction import (
    IntakeExtraction,
    materialize_extraction,
)
from jung.phases.intake.merge import merge_intake_record_patch_with_diagnostics
from jung.phases.intake.models import IntakeEvidence, IntakeRecord, IntakeRecordPatch
from jung.phases.transcript import TranscriptTurn

EVIDENCE_SCHEMA_VERSION = 2
MESSAGE_CANONICALIZATION = "ordered-role-content-json-v1"
STRUCTURED_REQUEST_CANONICALIZATION = "structured-request-sorted-json-v1"

AcceptedAttempt = Literal["initial", "correction"]
EVIDENCE_INTEGRITY_FAILURE = "category_c_evidence_integrity_failed"
EVIDENCE_SEMANTIC_FAILURE = "category_c_semantic_assertions_failed"
PROCESSOR_STATE_INVARIANT = "category_c_processor_state_invariant_failed"


def provider_messages_sha256(messages: Sequence[Mapping[str, Any]]) -> str:
    """SHA-256 of ordered provider-prepared ``{role, content}`` messages."""
    payload = [{"role": item["role"], "content": item["content"]} for item in messages]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def structured_request_sha256(
    *,
    structured_mode: str,
    response_format_or_schema_instruction: object,
) -> str:
    """SHA-256 of mode + exact response_format / schema instruction."""
    payload = {
        "structured_output_mode": structured_mode,
        "response_format_or_schema": response_format_or_schema_instruction,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MemoryDiagnosticRecorder:
    """In-memory diagnostic sink for eval digests; never writes files."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._id_counters: dict[str, int] = {}
        self._sequence = 0

    def next_id(self, prefix: str) -> str:
        count = self._id_counters.get(prefix, 0) + 1
        self._id_counters[prefix] = count
        return f"{prefix}-{count}"

    def record(self, kind: str, data: Mapping[str, Any] | None = None) -> None:
        self._sequence += 1
        self.events.append(
            {
                "sequence": self._sequence,
                "kind": kind,
                "context": current_diagnostic_context().as_dict(),
                "data": sanitize_value(dict(data or {})),
            }
        )


def _event_llm_call_id(event: Mapping[str, Any]) -> str | None:
    data = event.get("data") or {}
    context = event.get("context") or {}
    value = data.get("llm_call_id") or context.get("llm_call_id")
    return str(value) if value is not None else None


def _event_provider_attempt_id(event: Mapping[str, Any]) -> str | None:
    data = event.get("data") or {}
    value = data.get("provider_attempt_id")
    return str(value) if value is not None else None


def _event_sequence(event: Mapping[str, Any]) -> int:
    value = event.get("sequence")
    if isinstance(value, int):
        return value
    return 0


def digests_from_provider_request_data(
    data: Mapping[str, Any],
    *,
    structured_mode: StructuredOutputMode,
) -> dict[str, str]:
    """Extract provider message + structured-request digests from request data."""
    raw_messages = data.get("messages")
    messages: list[Mapping[str, Any]] = []
    if isinstance(raw_messages, Sequence) and not isinstance(
        raw_messages, (str, bytes)
    ):
        for item in raw_messages:
            if isinstance(item, Mapping) and "role" in item and "content" in item:
                messages.append(item)
    mode = structured_mode.value
    if structured_mode is StructuredOutputMode.PROMPT:
        structured_payload: object = messages[-1]["content"] if messages else ""
    else:
        structured_payload = data.get("response_format")
    return {
        "provider_messages_sha256": provider_messages_sha256(messages),
        "structured_request_sha256": structured_request_sha256(
            structured_mode=mode,
            response_format_or_schema_instruction=structured_payload,
        ),
    }


def digests_from_provider_request_event(
    data: Mapping[str, Any],
    *,
    structured_mode: StructuredOutputMode | None = None,
) -> dict[str, str]:
    mode = structured_mode
    if mode is None:
        raw_mode = data.get("structured_output_mode")
        mode = (
            StructuredOutputMode(raw_mode)
            if isinstance(raw_mode, str)
            else StructuredOutputMode.JSON_SCHEMA
        )
    return digests_from_provider_request_data(data, structured_mode=mode)


@dataclass(frozen=True, slots=True)
class CorrelatedProviderAttempt:
    attempt: AcceptedAttempt
    provider_attempt_id: str
    provider_messages_sha256: str
    structured_request_sha256: str
    status: str
    correction_trigger: str | None = None


@dataclass(frozen=True, slots=True)
class IntakePatchCorrelation:
    llm_call_id: str
    accepted_extraction: IntakeExtraction
    accepted_attempt: AcceptedAttempt
    provider_attempts: tuple[CorrelatedProviderAttempt, ...]
    initial_request_data: Mapping[str, Any]


def _resolve_accepted_event_task(
    event: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    context = event.get("context") or {}
    data = event.get("data") or {}
    context_task = context.get("llm_task") if isinstance(context, Mapping) else None
    data_task = data.get("task") if isinstance(data, Mapping) else None
    context_present = context_task is not None
    data_present = data_task is not None
    if context_present and not data_present:
        return str(context_task), None
    if not context_present and data_present:
        return str(data_task), None
    if context_present and data_present:
        if str(context_task) != str(data_task):
            return None, "accepted event context/data task conflict"
        return str(context_task), None
    return None, "accepted event missing task"


def correlate_intake_patch_call(  # noqa: C901
    recorder: MemoryDiagnosticRecorder,
    *,
    task: str = LLMTask.INTAKE_PATCH.value,
) -> tuple[IntakePatchCorrelation | None, list[str]]:
    """Correlate accepted intake_patch output to identity-keyed provider attempts."""
    errors: list[str] = []
    logical_kinds = {
        "llm.provider.request",
        "llm.provider.response",
        "llm.provider.error",
        "llm.output.accepted",
    }

    accepted_candidates = [
        event
        for event in recorder.events
        if event.get("kind") == "llm.output.accepted"
        and isinstance(event.get("data"), Mapping)
        and event["data"].get("output_type") == "IntakeExtraction"
    ]

    valid_accepted: list[dict[str, Any]] = []
    for event in accepted_candidates:
        resolved_task, task_error = _resolve_accepted_event_task(event)
        if task_error is not None:
            errors.append(f"{task}: {task_error}")
            continue
        if resolved_task != task:
            continue
        valid_accepted.append(dict(event))

    if not valid_accepted:
        if not errors:
            errors.append(f"{task}: no accepted IntakeExtraction for expected task")
        return None, errors

    if len(valid_accepted) != 1:
        errors.append(
            f"{task}: expected exactly one accepted IntakeExtraction, "
            f"got {len(valid_accepted)}"
        )
        return None, errors

    accepted_event = valid_accepted[0]
    llm_call_id = _event_llm_call_id(accepted_event)
    if llm_call_id is None:
        errors.append(f"{task}: accepted event missing llm_call_id")
        return None, errors

    accepted_data = accepted_event.get("data") or {}
    raw_result = accepted_data.get("result")
    if not isinstance(raw_result, Mapping):
        errors.append(f"{task}: accepted result is not a mapping")
        return None, errors
    try:
        accepted_extraction = IntakeExtraction.model_validate(raw_result)
    except Exception as exc:
        errors.append(f"{task}: accepted extraction invalid: {exc}")
        return None, errors

    call_events = [
        event
        for event in recorder.events
        if event.get("kind") in logical_kinds
        and _event_llm_call_id(event) == llm_call_id
    ]
    if not call_events:
        errors.append(f"{task}: no provider events for llm_call_id {llm_call_id!r}")
        return None, errors

    if any(_event_llm_call_id(event) is None for event in call_events):
        errors.append(f"{task}: provider/accepted event missing llm_call_id")
        return None, errors

    requests_by_id: dict[str, dict[str, Any]] = {}
    terminals_by_id: dict[str, list[dict[str, Any]]] = {}
    for event in call_events:
        kind = event.get("kind")
        if kind == "llm.output.accepted":
            continue
        attempt_id = _event_provider_attempt_id(event)
        if attempt_id is None:
            errors.append(f"{task}: provider event missing provider_attempt_id")
            continue
        if kind == "llm.provider.request":
            if attempt_id in requests_by_id:
                errors.append(f"{task}: duplicate provider request for {attempt_id!r}")
            requests_by_id[attempt_id] = dict(event)
        elif kind in {"llm.provider.response", "llm.provider.error"}:
            terminals_by_id.setdefault(attempt_id, []).append(dict(event))

    attempt_ids = set(requests_by_id) | set(terminals_by_id)
    if not attempt_ids:
        errors.append(f"{task}: missing provider request(s)")
        return None, errors

    ordered_rows: list[CorrelatedProviderAttempt] = []
    initial_request_data: Mapping[str, Any] | None = None
    for attempt_id in sorted(
        attempt_ids, key=lambda aid: _event_sequence(requests_by_id.get(aid, {}))
    ):
        request_event = requests_by_id.get(attempt_id)
        terminals = terminals_by_id.get(attempt_id, [])
        if request_event is None:
            errors.append(f"{task}: terminal without request for {attempt_id!r}")
            continue
        if len(terminals) != 1:
            errors.append(
                f"{task}: provider_attempt_id={attempt_id!r} expected exactly one "
                f"terminal, got {len(terminals)}"
            )
            continue
        request_data = request_event.get("data") or {}
        if not isinstance(request_data, Mapping):
            errors.append(f"{task}: provider request data invalid")
            continue
        request_task = request_data.get("task")
        if request_task != task:
            errors.append(
                f"{task}: provider request task mismatch for {attempt_id!r}: "
                f"expected {task!r}, got {request_task!r}"
            )
            continue
        attempt_label = request_data.get("attempt")
        if attempt_label not in {"initial", "correction"}:
            errors.append(
                f"{task}: illegal attempt label {attempt_label!r} for {attempt_id!r}"
            )
            continue
        terminal_event = terminals[0]
        terminal_kind = terminal_event.get("kind")
        terminal_data = terminal_event.get("data") or {}
        if not isinstance(terminal_data, Mapping):
            errors.append(f"{task}: provider terminal data invalid")
            continue
        terminal_task = terminal_data.get("task")
        terminal_attempt = terminal_data.get("attempt")
        if terminal_task != request_task or terminal_task != task:
            errors.append(f"{task}: provider terminal task mismatch for {attempt_id!r}")
            continue
        if terminal_attempt != attempt_label:
            errors.append(
                f"{task}: provider terminal attempt mismatch for {attempt_id!r}: "
                f"expected {attempt_label!r}, got {terminal_attempt!r}"
            )
            continue
        status = str(terminal_data.get("status", "unknown"))
        if terminal_kind == "llm.provider.response":
            if status != "success":
                errors.append(
                    f"{task}: provider response for {attempt_id!r} requires "
                    f"status=success, got {status!r}"
                )
        elif terminal_kind == "llm.provider.error":
            if status == "success":
                errors.append(
                    f"{task}: provider error for {attempt_id!r} must not have "
                    f"status=success"
                )
        structured_raw = request_data.get("structured_output_mode")
        structured_mode = (
            StructuredOutputMode(structured_raw)
            if isinstance(structured_raw, str)
            else StructuredOutputMode.JSON_SCHEMA
        )
        digests = digests_from_provider_request_data(
            request_data, structured_mode=structured_mode
        )
        correction_trigger = request_data.get("correction_trigger")
        if attempt_label == "initial":
            if initial_request_data is not None:
                errors.append(f"{task}: duplicate initial provider request")
            else:
                initial_request_data = request_data
        ordered_rows.append(
            CorrelatedProviderAttempt(
                attempt=attempt_label,  # type: ignore[arg-type]
                provider_attempt_id=attempt_id,
                provider_messages_sha256=digests["provider_messages_sha256"],
                structured_request_sha256=digests["structured_request_sha256"],
                status=status,
                correction_trigger=(
                    str(correction_trigger) if correction_trigger is not None else None
                ),
            )
        )

    attempt_sequence = [row.attempt for row in ordered_rows]
    if attempt_sequence not in (["initial"], ["initial", "correction"]):
        errors.append(f"{task}: illegal physical-attempt sequence {attempt_sequence!r}")

    if attempt_sequence == ["initial", "correction"]:
        correction_row = ordered_rows[1]
        if not correction_row.correction_trigger:
            errors.append(
                f"{task}: correction request missing non-empty correction_trigger"
            )
        initial_terminal = terminals_by_id[ordered_rows[0].provider_attempt_id][0]
        if initial_terminal.get("kind") == "llm.provider.error":
            initial_error_type = (initial_terminal.get("data") or {}).get("error_type")
            if initial_error_type != "InvalidLLMOutput":
                errors.append(
                    f"{task}: illegal correction predecessor error_type "
                    f"{initial_error_type!r}"
                )

    if initial_request_data is None:
        errors.append(f"{task}: missing unique initial provider request")
        return None, errors

    if ordered_rows:
        final_id = ordered_rows[-1].provider_attempt_id
        final_terminal = terminals_by_id.get(final_id, [None])[0]
        if final_terminal is None:
            errors.append(f"{task}: missing terminal for accepted attempt {final_id!r}")
        else:
            final_kind = final_terminal.get("kind")
            final_status = str((final_terminal.get("data") or {}).get("status", ""))
            if final_kind != "llm.provider.response":
                errors.append(
                    f"{task}: accepted attempt must terminate with "
                    f"llm.provider.response, got {final_kind!r}"
                )
            elif final_status != "success":
                errors.append(
                    f"{task}: accepted attempt requires status=success, "
                    f"got {final_status!r}"
                )

    if errors:
        return None, errors

    accepted_attempt = ordered_rows[-1].attempt
    return (
        IntakePatchCorrelation(
            llm_call_id=llm_call_id,
            accepted_extraction=accepted_extraction,
            accepted_attempt=accepted_attempt,
            provider_attempts=tuple(ordered_rows),
            initial_request_data=initial_request_data,
        ),
        [],
    )


def _quote_valid(quote: str | None, message: str) -> bool:
    if not quote:
        return False
    normalized_quote = normalize_content(quote)
    normalized_message = normalize_content(message)
    return bool(normalized_quote) and normalized_quote in normalized_message


def _raw_accepted_fields(
    extraction: IntakeExtraction,
    *,
    fixture: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in extraction.evidence:
        quote = candidate.evidence_quote
        rows.append(
            {
                "path": candidate.field.value,
                "status": candidate.response_status,
                "quote": quote,
                "quote_valid": _quote_valid(quote, fixture),
            }
        )
    return rows


def _medical_urgency_absent_raw(extraction: IntakeExtraction) -> bool:
    for candidate in extraction.evidence:
        if candidate.field.value == "safety.medical_urgency":
            return False
    return True


def _medical_urgency_absent_patch(patch: IntakeRecordPatch) -> bool:
    if patch.safety is None:
        return True
    evidence = patch.safety.medical_urgency
    return not (evidence.value or evidence.evidence_quote)


def _medical_urgency_absent_record(record: IntakeRecord) -> bool:
    evidence = record.safety.medical_urgency
    return not evidence.is_present()


def _iter_patch_paths(patch: IntakeRecordPatch) -> list[tuple[str, IntakeEvidence]]:
    paths: list[tuple[str, IntakeEvidence]] = []

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, IntakeEvidence):
            if value.value or value.evidence_quote:
                paths.append((prefix, value))
            return
        if isinstance(value, BaseModel):
            for name in type(value).model_fields:
                child = getattr(value, name)
                if child is not None:
                    walk(f"{prefix}.{name}" if prefix else name, child)

    if patch.presenting_problem is not None:
        walk("presenting_problem", patch.presenting_problem)
    if patch.safety is not None:
        walk("safety", patch.safety)
    if patch.coping is not None:
        walk("coping", patch.coping)
    if patch.goals is not None:
        walk("goals", patch.goals)
    return paths


def _changed_record_paths(before: IntakeRecord, after: IntakeRecord) -> tuple[str, ...]:
    before_map = dict(iter_record_evidence_paths(before))
    after_map = dict(iter_record_evidence_paths(after))
    paths = set(before_map) | set(after_map)
    return tuple(
        sorted(path for path in paths if before_map.get(path) != after_map.get(path))
    )


def build_evidence_stages(
    *,
    extraction: IntakeExtraction,
    pre_turn_record: IntakeRecord,
    user_turn: TranscriptTurn,
    prompted_item: str | None,
    fixture: str,
) -> dict[str, Any]:
    """Replay materialization/merge for staged Category C evidence fields."""
    materialization = materialize_extraction(
        extraction,
        latest_user_turn=user_turn,
        prompted_item=prompted_item,  # type: ignore[arg-type]
    )
    merge = merge_intake_record_patch_with_diagnostics(
        pre_turn_record,
        materialization.patch,
        latest_user_message=user_turn,
        source_message_sequence=user_turn.sequence,
    )
    merge_dropped_paths = {
        str(item.get("field_path", "")) for item in merge.drop_reasons
    }
    validation_retained = [
        path
        for path, _evidence in _iter_patch_paths(materialization.patch)
        if path not in merge_dropped_paths
    ]
    return {
        "raw_accepted_fields": _raw_accepted_fields(extraction, fixture=fixture),
        "validation_retained_paths": validation_retained,
        "materialization_dropped_paths": [
            str(item.get("field_path", "")) for item in materialization.drop_reasons
        ],
        "merge_dropped_paths": [
            str(item.get("field_path", "")) for item in merge.drop_reasons
        ],
        "merged_changed_paths": list(
            _changed_record_paths(pre_turn_record, merge.record)
        ),
        "raw_medical_urgency_absent": _medical_urgency_absent_raw(extraction),
        "validation_medical_urgency_absent": _medical_urgency_absent_patch(
            materialization.patch
        ),
        "merged_medical_urgency_absent": _medical_urgency_absent_record(merge.record),
        "merge_status": merge.status,
        "raw_evidence_count": materialization.raw_candidate_count,
        "retained_evidence_count": merge.retained_evidence_count,
        "dropped_evidence_count": merge.dropped_evidence_count,
        "record_changed": merge.record_changed,
    }


def canonical_fixture_digests(
    *,
    structured_mode: StructuredOutputMode,
    messages: Sequence[Mapping[str, str]],
) -> tuple[str, str]:
    response_format = response_format_for_mode(structured_mode, IntakeExtraction)
    if structured_mode is StructuredOutputMode.PROMPT:
        structured_payload: object = build_prompt_schema_instruction(IntakeExtraction)
    else:
        structured_payload = response_format
    return (
        provider_messages_sha256(messages),
        structured_request_sha256(
            structured_mode=structured_mode.value,
            response_format_or_schema_instruction=structured_payload,
        ),
    )


def provider_attempt_rows(
    attempts: Sequence[CorrelatedProviderAttempt],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for attempt in attempts:
        row: dict[str, Any] = {
            "attempt": attempt.attempt,
            "provider_attempt_id": attempt.provider_attempt_id,
            "provider_messages_sha256": attempt.provider_messages_sha256,
            "structured_request_sha256": attempt.structured_request_sha256,
            "status": attempt.status,
        }
        if attempt.correction_trigger is not None:
            row["correction_trigger"] = attempt.correction_trigger
        rows.append(row)
    return rows


def build_category_c_evidence_payload(
    *,
    semantic_assertions_passed: bool,
    evidence_integrity_passed: bool,
    model: str | None = None,
    sanitized_endpoint: str | None = None,
    structured_mode: str | None = None,
    prompt_version: str | None = None,
    extra_body: dict[str, object] | None = None,
    frozen_fixture: str | None = None,
    extraction_target: str | None = None,
    llm_call_id: str | None = None,
    raw_accepted_fields: list[dict[str, Any]] | None = None,
    validation_retained_paths: list[str] | None = None,
    materialization_dropped_paths: list[str] | None = None,
    merge_dropped_paths: list[str] | None = None,
    merged_changed_paths: list[str] | None = None,
    raw_medical_urgency_absent: bool | None = None,
    validation_medical_urgency_absent: bool | None = None,
    merged_medical_urgency_absent: bool | None = None,
    merge_status: str | None = None,
    raw_evidence_count: int | None = None,
    retained_evidence_count: int | None = None,
    dropped_evidence_count: int | None = None,
    record_changed: bool | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
    accepted_attempt: AcceptedAttempt | None = None,
    canonical_fixture_provider_messages_sha256: str | None = None,
    canonical_fixture_structured_request_sha256: str | None = None,
    canonical_matches_executed_messages: bool | None = None,
    canonical_matches_executed_structured: bool | None = None,
    primary_failure_code: str | None = None,
    primary_failure_exception_type: str | None = None,
    evidence_integrity_errors: list[str] | None = None,
) -> dict[str, Any]:
    """Build the mandatory Category C evidence payload (None for N/A on failure)."""
    success = semantic_assertions_passed and evidence_integrity_passed
    return {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "fingerprint_canonicalization_messages": MESSAGE_CANONICALIZATION,
        "fingerprint_canonicalization_structured": STRUCTURED_REQUEST_CANONICALIZATION,
        "semantic_assertions_passed": semantic_assertions_passed,
        "evidence_integrity_passed": evidence_integrity_passed,
        "success": success,
        "model": model,
        "sanitized_endpoint": sanitized_endpoint,
        "structured_mode": structured_mode,
        "prompt_version": prompt_version,
        "extra_body": extra_body,
        "frozen_fixture": frozen_fixture,
        "extraction_target": extraction_target,
        "llm_call_id": llm_call_id,
        "raw_accepted_fields": raw_accepted_fields,
        "validation_retained_paths": validation_retained_paths,
        "materialization_dropped_paths": materialization_dropped_paths,
        "merge_dropped_paths": merge_dropped_paths,
        "merged_changed_paths": merged_changed_paths,
        "raw_medical_urgency_absent": raw_medical_urgency_absent,
        "validation_medical_urgency_absent": validation_medical_urgency_absent,
        "merged_medical_urgency_absent": merged_medical_urgency_absent,
        "merge_status": merge_status,
        "raw_evidence_count": raw_evidence_count,
        "retained_evidence_count": retained_evidence_count,
        "dropped_evidence_count": dropped_evidence_count,
        "record_changed": record_changed,
        "provider_attempts": provider_attempts if provider_attempts is not None else [],
        "accepted_attempt": accepted_attempt,
        "canonical_fixture_provider_messages_sha256": (
            canonical_fixture_provider_messages_sha256
        ),
        "canonical_fixture_structured_request_sha256": (
            canonical_fixture_structured_request_sha256
        ),
        "canonical_matches_executed_messages": canonical_matches_executed_messages,
        "canonical_matches_executed_structured": canonical_matches_executed_structured,
        "primary_failure_code": primary_failure_code,
        "primary_failure_exception_type": primary_failure_exception_type,
        "evidence_integrity_errors": evidence_integrity_errors or [],
    }


def sanitize_evidence_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Sanitize a v2 evidence payload at the writer boundary."""
    return sanitize_value(dict(payload))  # type: ignore[return-value]


def write_category_c_evidence(*, run_dir: Path, payload: Mapping[str, Any]) -> None:
    """Create ``run_dir`` exclusively (0700) and write ``evidence.md`` as 0600."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        os.chmod(run_dir, 0o700)
    except OSError:
        pass
    sanitized = sanitize_evidence_payload(payload)
    lines = [
        "# Category C clear-risk-denial evidence",
        "",
        "```json",
        json.dumps(sanitized, indent=2, ensure_ascii=False, default=str),
        "```",
        "",
    ]
    evidence_path = run_dir / "evidence.md"
    with open_private_file(evidence_path, mode="w") as handle:
        handle.write("\n".join(lines))


def resolve_debug_run_dir() -> Path | None:
    """Return ``JUNG_DEBUG_RUN_DIR`` when set; path must not already exist."""
    raw = os.environ.get("JUNG_DEBUG_RUN_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.exists():
        raise ValueError(
            f"JUNG_DEBUG_RUN_DIR must not already exist (got existing path: {path})"
        )
    return path


def evaluate_evidence_integrity(
    *,
    correlation: IntakePatchCorrelation | None,
    correlation_errors: Sequence[str],
    canonical_messages_sha256: str,
    canonical_structured_sha256: str,
    stages: Mapping[str, Any] | None,
) -> tuple[bool, bool | None, bool | None, list[str]]:
    """Return integrity pass, message match, structured match, and error details."""
    errors = list(correlation_errors)
    if correlation is None:
        return False, None, None, errors

    initial = next(
        (row for row in correlation.provider_attempts if row.attempt == "initial"),
        None,
    )
    if initial is None:
        errors.append("missing initial provider attempt row")
        return False, None, None, errors

    messages_match = initial.provider_messages_sha256 == canonical_messages_sha256
    structured_match = initial.structured_request_sha256 == canonical_structured_sha256
    if not messages_match:
        errors.append("canonical_messages_digest_mismatch")
    if not structured_match:
        errors.append("canonical_structured_digest_mismatch")

    mandatory_stage_keys = (
        "raw_accepted_fields",
        "validation_retained_paths",
        "materialization_dropped_paths",
        "merge_dropped_paths",
        "merged_changed_paths",
        "raw_medical_urgency_absent",
        "validation_medical_urgency_absent",
        "merged_medical_urgency_absent",
        "merge_status",
        "raw_evidence_count",
        "retained_evidence_count",
    )
    if stages is None:
        errors.append("evidence_stages_unavailable")
    else:
        for key in mandatory_stage_keys:
            if stages.get(key) is None:
                errors.append(f"mandatory_stage_field_missing:{key}")

    passed = not errors and messages_match and structured_match and stages is not None
    return passed, messages_match, structured_match, errors


def raw_medical_urgency_absence(stages: Mapping[str, Any] | None) -> bool | None:
    """Tri-state raw medical-urgency absence from evidence stages."""
    if stages is None:
        return None
    value = stages.get("raw_medical_urgency_absent")
    return value if isinstance(value, bool) else None


def _group_failures(
    failures: list[BaseException],
    *,
    message: str,
) -> BaseException:
    if len(failures) == 1:
        return failures[0]
    return BaseExceptionGroup(message, failures)


def build_category_c_eval_failure(
    *,
    primary_exc: BaseException | None,
    evidence_finalization_exc: BaseException | None = None,
    processor_passed: bool,
    raw_absence: bool | None,
    effective_integrity_passed: bool,
    write_exc: BaseException | None = None,
) -> BaseException | None:
    """Return the pytest failure to raise, or None when the eval should pass."""
    if processor_passed != (primary_exc is None):
        return AssertionError(PROCESSOR_STATE_INVARIANT)

    if primary_exc is not None:
        grouped: list[BaseException] = [primary_exc]
        if evidence_finalization_exc is not None:
            grouped.append(evidence_finalization_exc)
        if write_exc is not None:
            grouped.append(write_exc)
        return _group_failures(
            grouped,
            message="category-c eval failures",
        )

    if evidence_finalization_exc is not None:
        grouped = [evidence_finalization_exc]
        if write_exc is not None:
            grouped.append(write_exc)
        return _group_failures(
            grouped,
            message="category-c eval failures",
        )

    failures: list[BaseException] = []
    if processor_passed and raw_absence is False:
        failures.append(AssertionError(EVIDENCE_SEMANTIC_FAILURE))
    if processor_passed and not effective_integrity_passed:
        failures.append(AssertionError(EVIDENCE_INTEGRITY_FAILURE))
    if write_exc is not None:
        failures.append(write_exc)
    if not failures:
        return None
    return _group_failures(failures, message="category-c eval failures")
