"""Intake-turn forensic correlation for simulation audit.md (Section B).

SQLite messages are authoritative for durable commit. Trace events attribute
attempts. Paths and reconstruction are audit-local only.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from jung.domain.text import normalize_content
from jung.phases.intake.completion import (
    IntakeItem,
    intake_record_completion_decision,
    missing_items_from_record,
)
from jung.phases.intake.extraction import (
    IntakeExtraction,
    materialize_extraction,
    prompted_item_for_extraction,
)
from jung.phases.intake.merge import (
    IntakePatchMergeStatus,
    merge_intake_record_patch_with_diagnostics,
)
from jung.phases.intake.models import IntakeEvidence, IntakeRecord, IntakeRecordPatch
from jung.phases.transcript import TranscriptTurn

UNKNOWN = "unknown_after_ambiguous_commit"

PathEvidence = tuple[str, ...] | Literal["unknown_after_ambiguous_commit"]
CountEvidence = int | Literal["unknown_after_ambiguous_commit"]
TargetEvidence = str | None | Literal["unknown_after_ambiguous_commit"]
MergeStatusEvidence = (
    IntakePatchMergeStatus | None | Literal["unknown_after_ambiguous_commit"]
)
DropReasonsEvidence = (
    tuple[tuple[str, str], ...] | Literal["unknown_after_ambiguous_commit"]
)
ExtractionRowsEvidence = (
    tuple[tuple[str, str, str, bool], ...] | Literal["unknown_after_ambiguous_commit"]
)

CommitStatus = Literal[
    "committed_exact",
    "committed_fallback",
    "committed_ambiguous",
    "uncommitted",
]

_LIFECYCLE_KINDS = frozenset(
    {
        "chat.turn.started",
        "chat.turn.completed",
        "chat.turn.failed",
        "chat.turn.cancelled",
    }
)
_FAILURE_MERGE_STATUSES = frozenset({"empty_after_validation", "merge_failure"})


def format_path_evidence(value: PathEvidence) -> str:
    if value == UNKNOWN:
        return UNKNOWN
    if not value:
        return "none"
    return ", ".join(f"`{path}`" for path in value)


def format_count_evidence(value: CountEvidence) -> str:
    if value == UNKNOWN:
        return UNKNOWN
    return str(value)


def format_target_evidence(value: TargetEvidence) -> str:
    if value == UNKNOWN:
        return UNKNOWN
    if value is None:
        return "none"
    return str(value)


def format_merge_status_evidence(value: MergeStatusEvidence) -> str:
    if value == UNKNOWN:
        return UNKNOWN
    if value is None:
        return "none"
    return str(value)


@dataclass(frozen=True, slots=True)
class IntakeAttemptReport:
    attempt_index: int  # 1-based
    request_id: str | None
    lifecycle_status: Literal["present", "lifecycle_missing"]
    attempt_outcome: Literal["completed", "failed", "cancelled", "unknown"]
    persisted_attempt: Literal["yes", "no", "unknown"]
    failure_code: str | None  # bounded project code or None
    extraction_target: TargetEvidence
    raw_count: CountEvidence
    retained_count: CountEvidence
    merge_status: MergeStatusEvidence
    planned_record_changed: bool | str  # bool or UNKNOWN
    persisted_record_changed: bool | str
    pre_turn_next_item: str | None | str  # may be UNKNOWN
    planned_next_item: str | None | str
    persisted_next_item: str | None | str
    planned_completeness_complete: bool | str
    planned_max_turn_completion_blocked: bool | str
    # (field, status, quote, quote_valid)
    extraction_rows: ExtractionRowsEvidence
    validation_retained_paths: PathEvidence
    persisted_changed_paths: PathEvidence
    materialization_dropped_paths: PathEvidence
    merge_dropped_paths: PathEvidence
    drop_reasons: DropReasonsEvidence
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntakeTurnReport:
    turn: int
    session_id: str
    client_message_id: str
    durable_commit: Literal["yes", "no"]
    commit_status: CommitStatus
    previous_assistant: str
    patient_message: str
    correlation_findings: tuple[str, ...]  # e.g. duplicate_completion_terminals
    attempts: tuple[IntakeAttemptReport, ...]


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fence_markdown(text: str) -> str:
    """Render text safely when it may contain pipes or newlines."""
    if not text:
        return text
    if "\n" in text or "```" in text:
        fence = "```"
        while fence in text:
            fence += "`"
        return f"{fence}\n{text}\n{fence}"
    if "|" in text:
        return text.replace("|", "\\|")
    return text


def iter_record_evidence_paths(
    record: IntakeRecord,
) -> Iterator[tuple[str, IntakeEvidence]]:
    """Yield ``(field_path, evidence)`` leaves for an intake record."""
    p = record.presenting_problem
    yield "presenting_problem.main_concern", p.main_concern
    for index, item in enumerate(p.symptoms):
        yield f"presenting_problem.symptoms[{index}]", item
    tc = p.time_course
    yield "presenting_problem.time_course.duration_or_onset", tc.duration_or_onset
    yield "presenting_problem.time_course.frequency", tc.frequency
    yield "presenting_problem.time_course.trajectory", tc.trajectory
    for index, item in enumerate(tc.triggers):
        yield f"presenting_problem.time_course.triggers[{index}]", item
    yield "presenting_problem.sleep_impact", p.sleep_impact
    yield "presenting_problem.functional_impairment", p.functional_impairment
    s = record.safety
    yield "safety.self_harm", s.self_harm
    yield "safety.harm_to_others", s.harm_to_others
    yield "safety.medical_urgency", s.medical_urgency
    c = record.coping
    for index, item in enumerate(c.attempted_strategies):
        yield f"coping.attempted_strategies[{index}]", item
    yield "coping.substances_or_medication", c.substances_or_medication
    g = record.goals
    for index, item in enumerate(g.therapy_goals):
        yield f"goals.therapy_goals[{index}]", item
    yield "goals.preferred_start", g.preferred_start


def iter_patch_evidence_paths(
    patch: IntakeRecordPatch,
) -> Iterator[tuple[str, IntakeEvidence]]:
    """Yield ``(field_path, evidence)`` leaves mirroring merge validation paths."""

    def _yield_if_present(
        path: str,
        evidence: IntakeEvidence,
    ) -> Iterator[tuple[str, IntakeEvidence]]:
        if evidence.value or evidence.evidence_quote:
            yield path, evidence

    if patch.presenting_problem is not None:
        p = patch.presenting_problem
        yield from _yield_if_present("presenting_problem.main_concern", p.main_concern)
        for index, item in enumerate(p.symptoms):
            yield from _yield_if_present(f"presenting_problem.symptoms[{index}]", item)
        yield from _yield_if_present("presenting_problem.sleep_impact", p.sleep_impact)
        yield from _yield_if_present(
            "presenting_problem.functional_impairment", p.functional_impairment
        )
        tc = p.time_course
        yield from _yield_if_present(
            "presenting_problem.time_course.duration_or_onset", tc.duration_or_onset
        )
        yield from _yield_if_present(
            "presenting_problem.time_course.frequency", tc.frequency
        )
        yield from _yield_if_present(
            "presenting_problem.time_course.trajectory", tc.trajectory
        )
        for index, item in enumerate(tc.triggers):
            yield from _yield_if_present(
                f"presenting_problem.time_course.triggers[{index}]", item
            )
    if patch.safety is not None:
        s = patch.safety
        yield from _yield_if_present("safety.self_harm", s.self_harm)
        yield from _yield_if_present("safety.harm_to_others", s.harm_to_others)
        yield from _yield_if_present("safety.medical_urgency", s.medical_urgency)
    if patch.coping is not None:
        c = patch.coping
        for index, item in enumerate(c.attempted_strategies):
            yield from _yield_if_present(f"coping.attempted_strategies[{index}]", item)
        yield from _yield_if_present(
            "coping.substances_or_medication", c.substances_or_medication
        )
    if patch.goals is not None:
        g = patch.goals
        for index, item in enumerate(g.therapy_goals):
            yield from _yield_if_present(f"goals.therapy_goals[{index}]", item)
        yield from _yield_if_present("goals.preferred_start", g.preferred_start)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _eval_count(eval_data: Mapping[str, Any] | None, key: str) -> CountEvidence:
    if eval_data is None or key not in eval_data:
        return UNKNOWN
    value = eval_data.get(key)
    if value is None:
        return UNKNOWN
    return int(value)


def _eval_merge_status(eval_data: Mapping[str, Any] | None) -> MergeStatusEvidence:
    if eval_data is None or "merge_status" not in eval_data:
        return UNKNOWN
    value = eval_data.get("merge_status")
    if value is None:
        return UNKNOWN
    return str(value)  # type: ignore[return-value]


def _eval_target(eval_data: Mapping[str, Any] | None) -> TargetEvidence:
    if eval_data is None or "extraction_target" not in eval_data:
        return UNKNOWN
    value = eval_data.get("extraction_target")
    if value is None:
        return None
    return str(value)


def _quote_valid(quote: str | None, message: str) -> bool:
    if not quote:
        return False
    normalized_quote = normalize_content(quote)
    normalized_message = normalize_content(message)
    return bool(normalized_quote) and normalized_quote in normalized_message


def _event_client_and_request(
    event: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    context = event.get("context") or {}
    if not isinstance(context, Mapping):
        return None, None
    return _optional_str(context.get("client_message_id")), _optional_str(
        context.get("request_id")
    )


def _is_intake_extraction_accepted(event: Mapping[str, Any]) -> bool:
    if event.get("kind") != "llm.output.accepted":
        return False
    context = event.get("context") or {}
    if not isinstance(context, Mapping):
        return False
    if context.get("llm_task") != "intake_patch":
        return False
    data = event.get("data") or {}
    if not isinstance(data, Mapping):
        return False
    return data.get("output_type") == "IntakeExtraction"


def _attempt_source_event(event: Mapping[str, Any]) -> bool:
    kind = event.get("kind")
    if kind in _LIFECYCLE_KINDS:
        return True
    if kind == "intake.turn.evaluated":
        return True
    return _is_intake_extraction_accepted(event)


def _request_ids_for_client(
    trace: Sequence[Mapping[str, Any]],
    *,
    client_message_id: str,
) -> list[str | None]:
    ordered: list[str | None] = []
    seen: set[str | None] = set()
    for event in trace:
        if not _attempt_source_event(event):
            continue
        event_client, request_id = _event_client_and_request(event)
        if event_client != client_message_id:
            continue
        if request_id in seen:
            continue
        seen.add(request_id)
        ordered.append(request_id)
    return ordered


def _lifecycle_events_for_attempt(
    trace: Sequence[Mapping[str, Any]],
    *,
    client_message_id: str,
    request_id: str | None,
) -> list[Mapping[str, Any]]:
    matched: list[Mapping[str, Any]] = []
    for event in trace:
        if event.get("kind") not in _LIFECYCLE_KINDS:
            continue
        event_client, event_request = _event_client_and_request(event)
        if event_client == client_message_id and event_request == request_id:
            matched.append(event)
    return matched


def _attempt_outcome_and_failure(
    lifecycle_events: Sequence[Mapping[str, Any]],
) -> tuple[Literal["completed", "failed", "cancelled", "unknown"], str | None]:
    kinds = {event.get("kind") for event in lifecycle_events}
    if "chat.turn.completed" in kinds:
        return "completed", None
    if "chat.turn.failed" in kinds:
        failure_code: str | None = None
        for event in lifecycle_events:
            if event.get("kind") != "chat.turn.failed":
                continue
            data = event.get("data") or {}
            if isinstance(data, Mapping) and data.get("error_code") is not None:
                failure_code = str(data["error_code"])
                break
        return "failed", failure_code
    if "chat.turn.cancelled" in kinds:
        return "cancelled", None
    return "unknown", None


def _matching_completion_events(
    trace: Sequence[Mapping[str, Any]],
    *,
    client_message_id: str,
    request_ids: Sequence[str | None],
) -> list[Mapping[str, Any]]:
    allowed = set(request_ids)
    matched: list[Mapping[str, Any]] = []
    for event in trace:
        if event.get("kind") != "chat.turn.completed":
            continue
        event_client, event_request = _event_client_and_request(event)
        if event_client == client_message_id and event_request in allowed:
            matched.append(event)
    return matched


def _evaluated_event_counts(
    trace: Sequence[Mapping[str, Any]],
    *,
    client_message_id: str,
) -> dict[str | None, int]:
    counts: dict[str | None, int] = {}
    for event in trace:
        if event.get("kind") != "intake.turn.evaluated":
            continue
        event_client, request_id = _event_client_and_request(event)
        if event_client != client_message_id:
            continue
        counts[request_id] = counts.get(request_id, 0) + 1
    return counts


def _extraction_event_counts(
    trace: Sequence[Mapping[str, Any]],
    *,
    client_message_id: str,
) -> dict[str | None, int]:
    counts: dict[str | None, int] = {}
    for event in trace:
        if not _is_intake_extraction_accepted(event):
            continue
        event_client, request_id = _event_client_and_request(event)
        if event_client != client_message_id:
            continue
        counts[request_id] = counts.get(request_id, 0) + 1
    return counts


def _evaluated_for_attempt(
    trace: Sequence[Mapping[str, Any]],
    *,
    client_message_id: str,
    request_id: str | None,
) -> Mapping[str, Any] | None:
    for event in trace:
        if event.get("kind") != "intake.turn.evaluated":
            continue
        event_client, event_request = _event_client_and_request(event)
        if event_client == client_message_id and event_request == request_id:
            data = event.get("data") or {}
            return data if isinstance(data, Mapping) else {}
    return None


def _extraction_for_attempt(
    trace: Sequence[Mapping[str, Any]],
    *,
    client_message_id: str,
    request_id: str | None,
) -> IntakeExtraction | None:
    for event in trace:
        if not _is_intake_extraction_accepted(event):
            continue
        event_client, event_request = _event_client_and_request(event)
        if event_client != client_message_id or event_request != request_id:
            continue
        data = event.get("data") or {}
        if not isinstance(data, Mapping):
            continue
        result = data.get("result")
        if isinstance(result, Mapping):
            return IntakeExtraction.model_validate(result)
    return None


def _changed_record_paths(
    before: IntakeRecord,
    after: IntakeRecord,
) -> tuple[str, ...]:
    before_map = dict(iter_record_evidence_paths(before))
    after_map = dict(iter_record_evidence_paths(after))
    paths = set(before_map) | set(after_map)
    return tuple(
        sorted(path for path in paths if before_map.get(path) != after_map.get(path))
    )


def _validation_retained_paths(
    patch: IntakeRecordPatch,
    merge_drop_reasons: Sequence[Mapping[str, str]],
) -> tuple[str, ...]:
    dropped = {
        str(item.get("field_path", ""))
        for item in merge_drop_reasons
        if isinstance(item, Mapping)
    }
    return tuple(
        path
        for path, _evidence in iter_patch_evidence_paths(patch)
        if path not in dropped
    )


def _decide_commit(
    *,
    durable: bool,
    request_ids: Sequence[str | None],
    attempt_outcomes: Sequence[Literal["completed", "failed", "cancelled", "unknown"]],
    matching_completions: Sequence[Mapping[str, Any]],
) -> tuple[
    CommitStatus,
    dict[str | None, Literal["yes", "no", "unknown"]],
    tuple[str, ...],
    list[str],
]:
    """Return commit_status, persisted_by_request, correlation findings, flags."""
    correlation: list[str] = []
    flags: list[str] = []
    persisted: dict[str | None, Literal["yes", "no", "unknown"]] = dict.fromkeys(
        request_ids, "no"
    )

    if not durable:
        return "uncommitted", persisted, (), flags

    if len(matching_completions) > 1:
        correlation.append("duplicate_completion_terminals")
        return (
            "committed_ambiguous",
            dict.fromkeys(request_ids, "unknown"),
            tuple(correlation),
            flags,
        )

    if len(matching_completions) == 1:
        _client, matched_request = _event_client_and_request(matching_completions[0])
        for request_id in request_ids:
            persisted[request_id] = "yes" if request_id == matched_request else "no"
        return "committed_exact", persisted, (), flags

    if len(request_ids) == 0:
        return "committed_ambiguous", {}, (), flags

    if len(request_ids) == 1:
        outcome = attempt_outcomes[0]
        if outcome in {"failed", "cancelled"}:
            return (
                "committed_ambiguous",
                {request_ids[0]: "unknown"},
                (),
                flags,
            )
        flags.append("missing_chat_completion_diagnostic")
        return (
            "committed_fallback",
            {request_ids[0]: "yes"},
            (),
            flags,
        )

    return (
        "committed_ambiguous",
        dict.fromkeys(request_ids, "unknown"),
        (),
        flags,
    )


@dataclass(frozen=True, slots=True)
class _ReplayResult:
    extraction_target: TargetEvidence
    raw_count: CountEvidence
    retained_count: CountEvidence
    merge_status: MergeStatusEvidence
    planned_record_changed: bool
    planned_next_item: str | None
    planned_completeness_complete: bool
    planned_max_turn_completion_blocked: bool
    merged_record: IntakeRecord
    extraction_rows: ExtractionRowsEvidence
    validation_retained_paths: PathEvidence
    persisted_changed_paths: PathEvidence
    materialization_dropped_paths: PathEvidence
    merge_dropped_paths: PathEvidence
    drop_reasons: DropReasonsEvidence
    flags: tuple[str, ...]


def _drop_observation_from_eval(
    eval_data: Mapping[str, Any] | None,
) -> tuple[PathEvidence, PathEvidence, DropReasonsEvidence]:
    if eval_data is None or "drop_reasons" not in eval_data:
        return UNKNOWN, UNKNOWN, UNKNOWN
    raw = eval_data.get("drop_reasons")
    if raw is None:
        return UNKNOWN, UNKNOWN, UNKNOWN
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return UNKNOWN, UNKNOWN, UNKNOWN
    if len(raw) == 0:
        return (), (), ()
    materialization_dropped: list[str] = []
    merge_dropped: list[str] = []
    drop_reasons: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            return UNKNOWN, UNKNOWN, UNKNOWN
        path = item.get("field_path")
        reason = item.get("reason")
        if path is None or reason is None:
            return UNKNOWN, UNKNOWN, UNKNOWN
        path_str = str(path)
        reason_str = str(reason)
        if not path_str or not reason_str:
            return UNKNOWN, UNKNOWN, UNKNOWN
        drop_reasons.append((path_str, reason_str))
        if path_str.startswith("evidence["):
            materialization_dropped.append(path_str)
        else:
            merge_dropped.append(path_str)
    return tuple(materialization_dropped), tuple(merge_dropped), tuple(drop_reasons)


def _drop_paths_from_eval(
    eval_data: Mapping[str, Any] | None,
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    materialization, merge, drops = _drop_observation_from_eval(eval_data)
    if materialization == UNKNOWN or merge == UNKNOWN or drops == UNKNOWN:
        return [], [], []
    return list(materialization), list(merge), list(drops)  # type: ignore[arg-type]


def _empty_replay(
    *,
    pre_turn_record: IntakeRecord,
    extraction_target: TargetEvidence,
    eval_data: Mapping[str, Any] | None,
) -> _ReplayResult:
    planned_record_changed = False
    planned_next_item = missing_items_from_record(pre_turn_record).next_required_item
    planned_complete = False
    planned_blocked = False
    raw_count: CountEvidence = UNKNOWN
    retained_count: CountEvidence = UNKNOWN
    merge_status: MergeStatusEvidence = UNKNOWN
    target = extraction_target
    drop_reasons: DropReasonsEvidence = UNKNOWN
    materialization_paths: PathEvidence = UNKNOWN
    merge_paths: PathEvidence = UNKNOWN
    if eval_data:
        if "extraction_target" in eval_data:
            target = _eval_target(eval_data)
        raw_count = _eval_count(eval_data, "raw_evidence_count")
        retained_count = _eval_count(eval_data, "retained_evidence_count")
        merge_status = _eval_merge_status(eval_data)
        if "record_changed" in eval_data:
            planned_record_changed = bool(eval_data.get("record_changed"))
        if "next_required_item" in eval_data:
            next_item = eval_data.get("next_required_item")
            planned_next_item = str(next_item) if next_item is not None else None
        if "completeness_complete" in eval_data:
            planned_complete = bool(eval_data.get("completeness_complete"))
        if "max_turn_completion_blocked" in eval_data:
            planned_blocked = bool(eval_data.get("max_turn_completion_blocked"))
        materialization_paths, merge_paths, drop_reasons = _drop_observation_from_eval(
            eval_data
        )
    return _ReplayResult(
        extraction_target=target,
        raw_count=raw_count,
        retained_count=retained_count,
        merge_status=merge_status,
        planned_record_changed=planned_record_changed,
        planned_next_item=planned_next_item,
        planned_completeness_complete=planned_complete,
        planned_max_turn_completion_blocked=planned_blocked,
        merged_record=pre_turn_record,
        extraction_rows=(),
        validation_retained_paths=(),
        persisted_changed_paths=(),
        materialization_dropped_paths=materialization_paths,
        merge_dropped_paths=merge_paths,
        drop_reasons=drop_reasons,
        flags=(),
    )


def _replay_attempt(  # noqa: C901
    *,
    pre_turn_record: IntakeRecord,
    patient_turn_count: int,
    patient_message: str,
    message_id: str,
    sequence: int,
    eval_data: Mapping[str, Any] | None,
    extraction: IntakeExtraction | None,
    state_unknown: bool,
) -> _ReplayResult:
    default_target = prompted_item_for_extraction(
        pre_turn_record,
        patient_turn_count=patient_turn_count,
    )
    if state_unknown:
        extraction_rows: ExtractionRowsEvidence = ()
        flags: list[str] = []
        raw_count: CountEvidence = UNKNOWN
        retained_count: CountEvidence = UNKNOWN
        merge_status: MergeStatusEvidence = UNKNOWN
        extraction_target: TargetEvidence = _eval_target(eval_data)
        materialization_paths: PathEvidence = UNKNOWN
        merge_paths: PathEvidence = UNKNOWN
        drop_reasons: DropReasonsEvidence = UNKNOWN
        if extraction is not None:
            raw_count = len(extraction.evidence)
            built_rows: list[tuple[str, str, str, bool]] = []
            for candidate in extraction.evidence:
                valid = _quote_valid(candidate.evidence_quote, patient_message)
                built_rows.append(
                    (
                        candidate.field.value,
                        candidate.response_status,
                        candidate.evidence_quote,
                        valid,
                    )
                )
                if valid:
                    flags.append("quote_found")
            extraction_rows = tuple(built_rows)
        if eval_data is not None:
            if extraction is None:
                raw_count = _eval_count(eval_data, "raw_evidence_count")
            retained_count = _eval_count(eval_data, "retained_evidence_count")
            merge_status = _eval_merge_status(eval_data)
            materialization_paths, merge_paths, drop_reasons = (
                _drop_observation_from_eval(eval_data)
            )
        return _ReplayResult(
            extraction_target=extraction_target,
            raw_count=raw_count,
            retained_count=retained_count,
            merge_status=merge_status,
            planned_record_changed=False,
            planned_next_item=None,
            planned_completeness_complete=False,
            planned_max_turn_completion_blocked=False,
            merged_record=pre_turn_record,
            extraction_rows=extraction_rows,
            validation_retained_paths=UNKNOWN,
            persisted_changed_paths=UNKNOWN,
            materialization_dropped_paths=materialization_paths,
            merge_dropped_paths=merge_paths,
            drop_reasons=drop_reasons,
            flags=tuple(dict.fromkeys(flags)),
        )

    if extraction is None:
        return _empty_replay(
            pre_turn_record=pre_turn_record,
            extraction_target=(
                str(default_target) if default_target is not None else None
            ),
            eval_data=eval_data,
        )

    prompted: IntakeItem | None = default_target
    extraction_target: TargetEvidence = (
        str(default_target) if default_target is not None else None
    )
    if eval_data and eval_data.get("extraction_target") is not None:
        extraction_target = str(eval_data["extraction_target"])
        prompted = extraction_target  # type: ignore[assignment]

    extraction_rows: list[tuple[str, str, str, bool]] = []
    flags: list[str] = []
    for candidate in extraction.evidence:
        valid = _quote_valid(candidate.evidence_quote, patient_message)
        extraction_rows.append(
            (
                candidate.field.value,
                candidate.response_status,
                candidate.evidence_quote,
                valid,
            )
        )
        if valid:
            flags.append("quote_found")

    turn_model = TranscriptTurn(
        message_id=UUID(message_id),
        sequence=sequence,
        role="user",
        content=patient_message,
    )
    materialization = materialize_extraction(
        extraction,
        latest_user_turn=turn_model,
        prompted_item=prompted,
    )
    merge = merge_intake_record_patch_with_diagnostics(
        pre_turn_record,
        materialization.patch,
        latest_user_message=turn_model,
        source_message_sequence=turn_model.sequence,
    )
    raw_count: CountEvidence = materialization.raw_candidate_count
    if merge.status == "merge_failure":
        merge_status: MergeStatusEvidence = "merge_failure"
    elif materialization.raw_candidate_count == 0:
        merge_status = "empty_patch"
    elif merge.retained_evidence_count == 0:
        merge_status = "empty_after_validation"
    else:
        merge_status = merge.status
    retained_count: CountEvidence = merge.retained_evidence_count
    planned_record_changed = merge.record_changed

    materialization_dropped = [
        str(reason.get("field_path", "")) for reason in materialization.drop_reasons
    ]
    merge_dropped = [str(reason.get("field_path", "")) for reason in merge.drop_reasons]
    drop_reasons = [
        (str(reason.get("field_path", "")), str(reason.get("reason", "")))
        for reason in (*materialization.drop_reasons, *merge.drop_reasons)
    ]
    validation_retained: PathEvidence = _validation_retained_paths(
        materialization.patch, merge.drop_reasons
    )
    persisted_changed: PathEvidence = _changed_record_paths(
        pre_turn_record, merge.record
    )

    if merge.retained_evidence_count > 0:
        flags.append("evidence_retained")
    if merge.record_changed:
        flags.append("record_advanced")
    if merge_status == "merge_failure":
        flags.append("merge_failure")

    extraction_failed = merge_status in _FAILURE_MERGE_STATUSES
    completeness = intake_record_completion_decision(
        merge.record,
        patient_turn_count,
        extraction_failed=extraction_failed,
    )
    planned_blocked = extraction_failed and completeness.max_turn_completion
    planned_complete = completeness.complete and not planned_blocked
    planned_next = completeness.next_required_item

    if eval_data:
        if eval_data.get("merge_status") is not None:
            merge_status = str(eval_data["merge_status"])  # type: ignore[assignment]
        override_raw = _eval_count(eval_data, "raw_evidence_count")
        if override_raw != UNKNOWN:
            raw_count = override_raw
        override_retained = _eval_count(eval_data, "retained_evidence_count")
        if override_retained != UNKNOWN:
            retained_count = override_retained
        if "record_changed" in eval_data:
            planned_record_changed = bool(eval_data.get("record_changed"))
        if "next_required_item" in eval_data:
            next_item = eval_data.get("next_required_item")
            planned_next = str(next_item) if next_item is not None else None
        if "completeness_complete" in eval_data:
            planned_complete = bool(eval_data.get("completeness_complete"))
        if "max_turn_completion_blocked" in eval_data:
            planned_blocked = bool(eval_data.get("max_turn_completion_blocked"))

    return _ReplayResult(
        extraction_target=extraction_target,
        raw_count=raw_count,
        retained_count=retained_count,
        merge_status=merge_status,
        planned_record_changed=planned_record_changed,
        planned_next_item=(str(planned_next) if planned_next is not None else None),
        planned_completeness_complete=planned_complete,
        planned_max_turn_completion_blocked=planned_blocked,
        merged_record=merge.record,
        extraction_rows=tuple(extraction_rows),
        validation_retained_paths=validation_retained,
        persisted_changed_paths=persisted_changed,
        materialization_dropped_paths=tuple(materialization_dropped),
        merge_dropped_paths=tuple(merge_dropped),
        drop_reasons=tuple(drop_reasons),
        flags=tuple(dict.fromkeys(flags)),
    )


def _apply_duplicate_extraction_matrix(
    *,
    eval_data: Mapping[str, Any] | None,
    pre_turn_next: str | None,
    flags: list[str],
) -> tuple[
    bool | str,
    str | None | str,
    PathEvidence,
    bool,
]:
    """Return persisted facts for committed attempts with conflicting extractions."""
    flags.append("duplicate_intake_extraction_accepted")
    if eval_data is None or "record_changed" not in eval_data:
        flags.append("committed_state_reconstruction_unavailable")
        return UNKNOWN, UNKNOWN, UNKNOWN, True

    record_changed = bool(eval_data.get("record_changed"))
    if not record_changed:
        if "next_required_item" in eval_data:
            evaluated_next = eval_data.get("next_required_item")
            evaluated_next_str = (
                str(evaluated_next) if evaluated_next is not None else None
            )
            prior_next_str = str(pre_turn_next) if pre_turn_next is not None else None
            if evaluated_next_str != prior_next_str:
                flags.append("evaluated_next_item_conflicts_with_prior_record")
        return False, pre_turn_next, (), False

    flags.append("committed_state_reconstruction_unavailable")
    if "next_required_item" in eval_data:
        next_item = eval_data.get("next_required_item")
        persisted_next: str | None | str = (
            str(next_item) if next_item is not None else None
        )
    else:
        persisted_next = UNKNOWN
    return True, persisted_next, UNKNOWN, True


def _apply_missing_extraction_matrix(
    *,
    eval_data: Mapping[str, Any] | None,
    pre_turn_next: str | None,
    flags: list[str],
) -> tuple[
    bool | str,
    str | None | str,
    PathEvidence,
    bool,
]:
    """Return persisted_record_changed, persisted_next_item, paths, latch_unknown."""
    if eval_data is None or "record_changed" not in eval_data:
        flags.append("committed_state_reconstruction_unavailable")
        return UNKNOWN, UNKNOWN, UNKNOWN, True

    record_changed = bool(eval_data.get("record_changed"))
    if not record_changed:
        if "next_required_item" in eval_data:
            evaluated_next = eval_data.get("next_required_item")
            evaluated_next_str = (
                str(evaluated_next) if evaluated_next is not None else None
            )
            prior_next_str = str(pre_turn_next) if pre_turn_next is not None else None
            if evaluated_next_str != prior_next_str:
                flags.append("evaluated_next_item_conflicts_with_prior_record")
        return False, pre_turn_next, (), False

    flags.append("missing_accepted_extraction_for_committed_change")
    if "next_required_item" in eval_data:
        next_item = eval_data.get("next_required_item")
        persisted_next: str | None | str = (
            str(next_item) if next_item is not None else None
        )
    else:
        persisted_next = UNKNOWN
    return True, persisted_next, UNKNOWN, True


def build_intake_turn_reports(  # noqa: C901
    *,
    trace: Sequence[Mapping[str, Any]],
    snapshot_path: Path | None,
) -> tuple[IntakeTurnReport, ...]:
    if snapshot_path is None or not snapshot_path.is_file():
        return ()

    conn = _connect_readonly(snapshot_path)
    try:
        intake_session = conn.execute(
            "SELECT id FROM sessions WHERE kind = 'intake' ORDER BY started_at LIMIT 1"
        ).fetchone()
        if intake_session is None:
            return ()
        session_id = str(intake_session["id"])
        rows = conn.execute(
            "SELECT id, sequence, role, content, client_message_id "
            "FROM messages WHERE session_id = ? ORDER BY sequence",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    assistant_clients = {
        str(row["client_message_id"]) for row in rows if row["role"] == "assistant"
    }

    durable_record = IntakeRecord()
    ambiguous_seen = False
    reports: list[IntakeTurnReport] = []
    turn = 0
    previous_assistant = ""

    for row in rows:
        if row["role"] != "user":
            if row["role"] == "assistant":
                previous_assistant = str(row["content"])
            continue

        turn += 1
        client_message_id = str(row["client_message_id"])
        patient_message = str(row["content"])
        durable = client_message_id in assistant_clients
        durable_commit: Literal["yes", "no"] = "yes" if durable else "no"
        pre_turn_record = durable_record
        pre_turn_next = missing_items_from_record(pre_turn_record).next_required_item
        state_unknown = ambiguous_seen

        request_ids = _request_ids_for_client(
            trace, client_message_id=client_message_id
        )
        synthetic_shell = False
        if not request_ids:
            request_ids = [None]
            synthetic_shell = True

        attempt_meta: list[
            tuple[
                str | None,
                Literal["present", "lifecycle_missing"],
                Literal["completed", "failed", "cancelled", "unknown"],
                str | None,
            ]
        ] = []
        outcomes: list[Literal["completed", "failed", "cancelled", "unknown"]] = []
        for request_id in request_ids:
            if synthetic_shell:
                lifecycle: list[Mapping[str, Any]] = []
            else:
                lifecycle = _lifecycle_events_for_attempt(
                    trace,
                    client_message_id=client_message_id,
                    request_id=request_id,
                )
            lifecycle_status: Literal["present", "lifecycle_missing"] = (
                "present" if lifecycle else "lifecycle_missing"
            )
            outcome, failure_code = _attempt_outcome_and_failure(lifecycle)
            outcomes.append(outcome)
            attempt_meta.append((request_id, lifecycle_status, outcome, failure_code))

        matching_completions = (
            []
            if synthetic_shell
            else _matching_completion_events(
                trace,
                client_message_id=client_message_id,
                request_ids=request_ids,
            )
        )
        commit_status, persisted_by_request, correlation, commit_flags = _decide_commit(
            durable=durable,
            request_ids=[] if synthetic_shell else request_ids,
            attempt_outcomes=[] if synthetic_shell else outcomes,
            matching_completions=matching_completions,
        )
        if synthetic_shell:
            if durable:
                commit_status = "committed_ambiguous"
                persisted_by_request = {None: "unknown"}
            else:
                commit_status = "uncommitted"
                persisted_by_request = {None: "no"}

        is_first_ambiguous = (
            commit_status == "committed_ambiguous" and not state_unknown
        )
        is_latched_turn = state_unknown
        attempt_reports: list[IntakeAttemptReport] = []
        persisted_merge_record: IntakeRecord | None = None
        latch_from_missing_extraction = False
        latch_from_duplicate_extraction = False

        evaluated_counts = _evaluated_event_counts(
            trace, client_message_id=client_message_id
        )
        extraction_counts = _extraction_event_counts(
            trace, client_message_id=client_message_id
        )

        for index, (request_id, lifecycle_status, outcome, failure_code) in enumerate(
            attempt_meta, start=1
        ):
            eval_count = 0 if synthetic_shell else evaluated_counts.get(request_id, 0)
            extraction_count = (
                0 if synthetic_shell else extraction_counts.get(request_id, 0)
            )
            duplicate_evaluated = eval_count > 1 and request_id is not None
            legacy_evaluated_ambiguous = request_id is None and eval_count > 1
            duplicate_extraction = extraction_count > 1

            eval_data = None
            if not synthetic_shell and eval_count == 1:
                eval_data = _evaluated_for_attempt(
                    trace,
                    client_message_id=client_message_id,
                    request_id=request_id,
                )

            extraction = None
            if not synthetic_shell and extraction_count == 1:
                extraction = _extraction_for_attempt(
                    trace,
                    client_message_id=client_message_id,
                    request_id=request_id,
                )

            ambiguous_evaluated = duplicate_evaluated or legacy_evaluated_ambiguous
            replay = _replay_attempt(
                pre_turn_record=pre_turn_record,
                patient_turn_count=turn,
                patient_message=patient_message,
                message_id=str(row["id"]),
                sequence=int(row["sequence"]),
                eval_data=eval_data,
                extraction=extraction,
                state_unknown=state_unknown,
            )
            persisted_attempt = persisted_by_request.get(request_id, "no")
            flags = list(replay.flags)
            flags.extend(commit_flags)

            if duplicate_evaluated:
                flags.append("duplicate_intake_turn_evaluated")
            if legacy_evaluated_ambiguous:
                flags.append("legacy_intake_turn_evaluated_attribution_ambiguous")

            extraction_rows: ExtractionRowsEvidence = replay.extraction_rows
            raw_count: CountEvidence = replay.raw_count
            retained_count: CountEvidence = replay.retained_count
            merge_status: MergeStatusEvidence = replay.merge_status
            extraction_target: TargetEvidence = replay.extraction_target
            validation_paths: PathEvidence = replay.validation_retained_paths
            materialization_paths: PathEvidence = replay.materialization_dropped_paths
            merge_paths: PathEvidence = replay.merge_dropped_paths
            drop_reasons: DropReasonsEvidence = replay.drop_reasons

            if ambiguous_evaluated and not state_unknown:
                retained_count = UNKNOWN
                merge_status = UNKNOWN
                extraction_target = UNKNOWN
                materialization_paths = UNKNOWN
                merge_paths = UNKNOWN
                drop_reasons = UNKNOWN

            if duplicate_extraction:
                extraction_rows = UNKNOWN
                raw_count = UNKNOWN
                validation_paths = UNKNOWN
                if not eval_data:
                    retained_count = UNKNOWN
                    merge_status = UNKNOWN
                    materialization_paths = UNKNOWN
                    merge_paths = UNKNOWN
                    drop_reasons = UNKNOWN

            missing_extraction_committed = (
                extraction is None
                and not duplicate_extraction
                and persisted_attempt == "yes"
                and not state_unknown
            )
            duplicate_extraction_committed = (
                duplicate_extraction
                and persisted_attempt == "yes"
                and not state_unknown
            )

            if is_latched_turn:
                planned_record_changed = UNKNOWN
                pre_turn_next_item = UNKNOWN
                planned_next_item = UNKNOWN
                planned_completeness = UNKNOWN
                planned_blocked = UNKNOWN
                validation_paths = UNKNOWN
                # preserve materialization_paths, merge_paths, drop_reasons from replay
                persisted_record_changed = UNKNOWN
                persisted_next_item = UNKNOWN
                persisted_paths = UNKNOWN
            elif is_first_ambiguous:
                planned_record_changed = replay.planned_record_changed
                pre_turn_next_item = pre_turn_next
                planned_next_item = replay.planned_next_item
                planned_completeness = replay.planned_completeness_complete
                planned_blocked = replay.planned_max_turn_completion_blocked
                persisted_record_changed = UNKNOWN
                persisted_next_item = UNKNOWN
                persisted_paths = UNKNOWN
            else:
                planned_record_changed = replay.planned_record_changed
                pre_turn_next_item = pre_turn_next
                planned_next_item = replay.planned_next_item
                planned_completeness = replay.planned_completeness_complete
                planned_blocked = replay.planned_max_turn_completion_blocked
                persisted_record_changed = False
                persisted_next_item = pre_turn_next
                persisted_paths = ()

                if duplicate_extraction_committed:
                    (
                        persisted_record_changed,
                        persisted_next_item,
                        persisted_paths,
                        latch_from_duplicate_extraction,
                    ) = _apply_duplicate_extraction_matrix(
                        eval_data=eval_data,
                        pre_turn_next=pre_turn_next,
                        flags=flags,
                    )
                elif missing_extraction_committed:
                    (
                        persisted_record_changed,
                        persisted_next_item,
                        persisted_paths,
                        latch_from_missing_extraction,
                    ) = _apply_missing_extraction_matrix(
                        eval_data=eval_data,
                        pre_turn_next=pre_turn_next,
                        flags=flags,
                    )
                elif persisted_attempt == "yes" and not duplicate_extraction:
                    persisted_record_changed = replay.planned_record_changed
                    persisted_next_item = replay.planned_next_item
                    persisted_paths = replay.persisted_changed_paths
                    persisted_merge_record = replay.merged_record
                elif persisted_attempt == "unknown":
                    persisted_record_changed = UNKNOWN
                    persisted_next_item = UNKNOWN
                    persisted_paths = UNKNOWN

            attempt_reports.append(
                IntakeAttemptReport(
                    attempt_index=index,
                    request_id=request_id,
                    lifecycle_status=lifecycle_status,
                    attempt_outcome=outcome,
                    persisted_attempt=persisted_attempt,
                    failure_code=failure_code,
                    extraction_target=extraction_target,
                    raw_count=raw_count,
                    retained_count=retained_count,
                    merge_status=merge_status,
                    planned_record_changed=planned_record_changed,
                    persisted_record_changed=persisted_record_changed,
                    pre_turn_next_item=pre_turn_next_item,
                    planned_next_item=planned_next_item,
                    persisted_next_item=persisted_next_item,
                    planned_completeness_complete=planned_completeness,
                    planned_max_turn_completion_blocked=planned_blocked,
                    extraction_rows=extraction_rows,
                    validation_retained_paths=validation_paths,
                    persisted_changed_paths=persisted_paths,
                    materialization_dropped_paths=materialization_paths,
                    merge_dropped_paths=merge_paths,
                    drop_reasons=drop_reasons,
                    flags=tuple(dict.fromkeys(flags)),
                )
            )

        if (
            commit_status in {"committed_exact", "committed_fallback"}
            and persisted_merge_record is not None
            and not state_unknown
            and not latch_from_missing_extraction
            and not latch_from_duplicate_extraction
        ):
            durable_record = persisted_merge_record

        if (
            commit_status == "committed_ambiguous"
            or latch_from_missing_extraction
            or latch_from_duplicate_extraction
        ):
            ambiguous_seen = True

        reports.append(
            IntakeTurnReport(
                turn=turn,
                session_id=session_id,
                client_message_id=client_message_id,
                durable_commit=durable_commit,
                commit_status=commit_status,
                previous_assistant=previous_assistant,
                patient_message=patient_message,
                correlation_findings=correlation,
                attempts=tuple(attempt_reports),
            )
        )

    return tuple(reports)


def intake_evaluated_coverage_findings(
    *,
    trace: Sequence[Mapping[str, Any]],
    intake_reports: Sequence[IntakeTurnReport],
) -> tuple[str, ...]:
    """Return bounded evaluated-event coverage warnings for audit Section B."""
    evaluated_counts: dict[tuple[str, str | None], int] = {}
    for event in trace:
        if event.get("kind") != "intake.turn.evaluated":
            continue
        client_id, request_id = _event_client_and_request(event)
        if client_id is None:
            continue
        key = (client_id, request_id)
        evaluated_counts[key] = evaluated_counts.get(key, 0) + 1

    findings: list[str] = []
    duplicate_reported: set[tuple[str, str | None]] = set()

    for report in intake_reports:
        client_id = report.client_message_id
        is_synthetic = not _request_ids_for_client(trace, client_message_id=client_id)

        if is_synthetic:
            if report.durable_commit == "yes":
                findings.append(
                    f"WARNING: evaluated_coverage_unknown_legacy_shell "
                    f"(turn {report.turn}, client `{client_id}`)"
                )
            continue

        none_count = evaluated_counts.get((client_id, None), 0)
        if none_count > 1:
            findings.append(
                f"WARNING: legacy intake.turn.evaluated attribution ambiguity "
                f"(turn {report.turn}, client `{client_id}`, {none_count} events "
                f"with request_id=null)"
            )

        for attempt in report.attempts:
            key = (client_id, attempt.request_id)
            count = evaluated_counts.get(key, 0)

            if (
                attempt.request_id is not None
                and count > 1
                and key not in duplicate_reported
            ):
                duplicate_reported.add(key)
                findings.append(
                    f"WARNING: duplicate intake.turn.evaluated "
                    f"(turn {report.turn}, request `{attempt.request_id}`, "
                    f"{count} events)"
                )
            elif attempt.persisted_attempt == "yes" and count == 0:
                findings.append(
                    f"WARNING: missing intake.turn.evaluated "
                    f"(turn {report.turn}, request `{attempt.request_id}`)"
                )

        if report.commit_status == "committed_ambiguous":
            unknown_attempts = [
                attempt
                for attempt in report.attempts
                if attempt.persisted_attempt == "unknown"
            ]
            if unknown_attempts:
                any_evaluated = any(
                    evaluated_counts.get((client_id, attempt.request_id), 0) > 0
                    for attempt in report.attempts
                )
                if not any_evaluated:
                    findings.append(
                        f"WARNING: missing intake.turn.evaluated evidence "
                        f"for committed-ambiguous turn {report.turn} "
                        f"(client `{client_id}`)"
                    )
                else:
                    findings.append(
                        f"WARNING: intake.turn.evaluated attribution ambiguity "
                        f"for committed-ambiguous turn {report.turn} "
                        f"(client `{client_id}`)"
                    )

    return tuple(findings)
