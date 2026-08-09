"""AI-agent debug bundle artifacts for explicit diagnostic runs.

Depends on ``jung.diagnostics``; diagnostics must not import this module.
Composition orchestrates manifest/finalization around the application lifetime.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any
from uuid import UUID

from jung.diagnostics import (
    SCHEMA_VERSION,
    DiagnosticRecorder,
    _safe_exception_message,
    sanitize_url,
    sanitize_value,
    write_private_text,
)
from jung.domain.errors import InvariantViolation
from jung.domain.models import MessageRole, OperationStatus
from jung.llm.gateway import ModelPolicy
from jung.persistence.sqlite_store import SCHEMA_VERSION as DB_SCHEMA_VERSION
from jung.persistence.sqlite_store import SQLiteStore

_CONTEXT_ID_KEYS = (
    "session_id",
    "operation_id",
    "client_message_id",
    "request_id",
    "llm_call_id",
)
_PAYLOAD_ID_KEYS = (
    "session_id",
    "operation_id",
    "plan_id",
    "source_session_id",
)


@dataclass(frozen=True, slots=True)
class ManifestLLMInfo:
    provider_url: str
    tasks: Mapping[str, Mapping[str, str]]


def build_manifest_llm_info(
    *,
    provider_url: str,
    policies: Mapping[Any, ModelPolicy],
) -> ManifestLLMInfo:
    tasks: dict[str, dict[str, str]] = {}
    for task, policy in sorted(policies.items(), key=lambda item: item[0].value):
        tasks[task.value] = {
            "model": policy.model,
            "structured_output_mode": policy.structured_output_mode.value,
        }
    return ManifestLLMInfo(
        provider_url=sanitize_url(provider_url),
        tasks=tasks,
    )


def package_version() -> str | None:
    try:
        return metadata.version("jung")
    except Exception:
        return None


def _matching_git_root(source: Path) -> Path | None:
    """Return the Jung source checkout root for ``source``, if any.

    Prefer ``None`` over a wrong SHA: only accept a Git root when this module
    resolves to ``<root>/src/jung/debug_bundle.py``.
    """
    for candidate in source.parents:
        if not (candidate / ".git").exists():
            continue
        expected = candidate / "src" / "jung" / "debug_bundle.py"
        if expected.exists() and expected.resolve() == source:
            return candidate
        return None
    return None


def git_commit() -> str | None:
    source = Path(__file__).resolve()
    root = _matching_git_root(source)
    if root is None:
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def write_manifest(
    recorder: DiagnosticRecorder,
    *,
    llm: ManifestLLMInfo,
    started_at: datetime | None = None,
) -> None:
    """Write startup-critical ``manifest.json`` (raises on failure)."""
    payload = {
        "run_id": str(recorder.run_id),
        "diagnostic_schema_version": SCHEMA_VERSION,
        "started_at": (started_at or datetime.now(UTC)).isoformat(),
        "jung_version": package_version(),
        "git_commit": git_commit(),
        "python_version": sys.version.split()[0],
        "database_schema_version_expected": DB_SCHEMA_VERSION,
        "llm": {
            "provider_url": llm.provider_url,
            "tasks": dict(llm.tasks),
        },
    }
    sanitized = sanitize_value(payload, secret_values=recorder.secret_values)
    write_private_text(
        recorder.run_dir / "manifest.json",
        json.dumps(sanitized, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
    )


def load_trace_events(run_dir: Path) -> list[dict[str, Any]]:
    path = Path(run_dir) / "trace.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def extract_touched_ids(events: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    """Extract IDs only from diagnostic context and known lifecycle payload fields."""
    collected: dict[str, set[str]] = {
        "session_id": set(),
        "operation_id": set(),
        "plan_id": set(),
    }
    for event in events:
        context = event.get("context")
        if isinstance(context, Mapping):
            for key in _CONTEXT_ID_KEYS:
                value = context.get(key)
                if isinstance(value, str) and value:
                    if key in collected:
                        collected[key].add(value)
                    elif key == "session_id":
                        collected["session_id"].add(value)
        data = event.get("data")
        if not isinstance(data, Mapping):
            continue
        for key in _PAYLOAD_ID_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value:
                if key == "source_session_id":
                    collected["session_id"].add(value)
                elif key in collected:
                    collected[key].add(value)
    return collected


def _sort_key_uuid(value: str) -> str:
    return value


def _model_dump(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def build_state_projection(
    store: SQLiteStore,
    *,
    touched: Mapping[str, set[str]],
) -> dict[str, Any]:
    try:
        facts = store.load_snapshot_facts()
        workflow = {
            "stage": facts.stage.value,
            "integrity_error": None,
        }
    except InvariantViolation as exc:
        workflow = {
            "stage": None,
            "integrity_error": _safe_exception_message(exc),
        }

    stored_profile = store.get_profile()
    current_plan = store.get_current_plan()
    active_session = store.get_active_session()
    current_operation = store.get_current_operation()

    session_ids = set(touched.get("session_id", set()))
    if active_session is not None:
        session_ids.add(str(active_session.id))
    if current_operation is not None:
        session_ids.add(str(current_operation.source_session_id))

    operation_ids = set(touched.get("operation_id", set()))
    if current_operation is not None:
        operation_ids.add(str(current_operation.id))

    sessions: list[Any] = []
    plans_by_id: dict[str, Any] = {}
    messages_by_session: dict[str, list[Any]] = {}
    for session_id in sorted(session_ids, key=_sort_key_uuid):
        session = store.get_session(UUID(session_id))
        if session is None:
            continue
        sessions.append(_model_dump(session))
        messages_by_session[session_id] = [
            _model_dump(message) for message in store.list_messages(UUID(session_id))
        ]
        for plan in store.list_plans_for_session(UUID(session_id)):
            plans_by_id[str(plan.id)] = _model_dump(plan)

    if current_plan is not None:
        plans_by_id[str(current_plan.id)] = _model_dump(current_plan)

    operations: list[Any] = []
    for operation_id in sorted(operation_ids, key=_sort_key_uuid):
        operation = store.get_operation(UUID(operation_id))
        if operation is not None:
            operations.append(_model_dump(operation))

    profile_payload = None
    if stored_profile is not None:
        profile_payload = _model_dump(stored_profile)

    return {
        "workflow": workflow,
        "profile": profile_payload,
        "sessions": sessions,
        "messages_by_session": messages_by_session,
        "plans": [
            plans_by_id[plan_id] for plan_id in sorted(plans_by_id, key=_sort_key_uuid)
        ],
        "operations": operations,
    }


def build_transcript_markdown(
    store: SQLiteStore,
    *,
    session_ids: set[str],
) -> str:
    lines: list[str] = ["# Durable transcript", ""]
    if not session_ids:
        lines.append("_No touched sessions._")
        lines.append("")
        return "\n".join(lines)

    for session_id in sorted(session_ids, key=_sort_key_uuid):
        session = store.get_session(UUID(session_id))
        lines.append(f"## Session `{session_id}`")
        lines.append("")
        if session is None:
            lines.append("_Session not found._")
            lines.append("")
            continue
        messages = store.list_messages(UUID(session_id))
        if not messages:
            lines.append("_No persisted messages._")
            lines.append("")
            continue
        for message in messages:
            lines.append(f"[{message.sequence}] {message.role.value}")
            lines.append(message.content)
            lines.append("")
    return "\n".join(lines)


def _trace_has_kind(events: Sequence[Mapping[str, Any]], kind: str) -> bool:
    return any(event.get("kind") == kind for event in events)


def classify_unresolved_problems(
    *,
    recorder: DiagnosticRecorder,
    events: Sequence[Mapping[str, Any]],
    state: Mapping[str, Any],
    primary_exception: BaseException | None,
    cleanup_exception: BaseException | None,
) -> list[str]:
    problems: list[str] = []
    if primary_exception is not None:
        problems.append(
            "primary exception: "
            f"{type(primary_exception).__name__}: "
            f"{_safe_exception_message(primary_exception)}"
        )
    if cleanup_exception is not None:
        problems.append(
            "cleanup exception: "
            f"{type(cleanup_exception).__name__}: "
            f"{_safe_exception_message(cleanup_exception)}"
        )
    if recorder.run_failed:
        problems.append("recorder.run_failed is set")
    if recorder.write_failed:
        problems.append("recorder.write_failed: trace evidence may be incomplete")
    workflow = state.get("workflow")
    if isinstance(workflow, Mapping) and workflow.get("integrity_error"):
        problems.append(f"workflow.integrity_error: {workflow['integrity_error']}")
    if _trace_has_kind(events, "task.failed"):
        problems.append("task.failed present in trace")
    if _trace_has_kind(events, "task.shutdown_timeout"):
        problems.append("task.shutdown_timeout present in trace")
    if _trace_has_kind(events, "runtime.error"):
        problems.append("runtime.error present in trace")

    # Open session with trailing USER = unanswered conversational work.
    sessions = {
        session.get("id"): session
        for session in (state.get("sessions") or [])
        if isinstance(session, Mapping) and isinstance(session.get("id"), str)
    }
    messages_by_session = state.get("messages_by_session") or {}
    if isinstance(messages_by_session, Mapping):
        for session_id, messages in messages_by_session.items():
            if not isinstance(session_id, str) or not isinstance(messages, list):
                continue
            session = sessions.get(session_id)
            if session is None or session.get("ended_at") is not None:
                continue
            if not messages:
                continue
            latest = messages[-1]
            if not isinstance(latest, Mapping):
                continue
            if latest.get("role") == MessageRole.USER.value:
                problems.append(
                    "unanswered user message on open session "
                    f"{session_id} client_message_id={latest.get('client_message_id')}"
                )

    for operation in state.get("operations") or []:
        if not isinstance(operation, Mapping):
            continue
        status = operation.get("status")
        operation_id = operation.get("id")
        if status == OperationStatus.FAILED.value:
            problems.append(
                f"unresolved operation {operation_id} status=failed "
                f"error_code={operation.get('error_code')}"
            )
        elif status in {
            OperationStatus.PENDING.value,
            OperationStatus.RUNNING.value,
        }:
            problems.append(
                f"incomplete/recoverable operation {operation_id} status={status}"
            )

    return problems


def build_failure_summary(
    *,
    problems: Sequence[str],
    events: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# Failure summary",
        "",
        "Unresolved / incomplete diagnostic evidence:",
        "",
    ]
    for problem in problems:
        lines.append(f"- {problem}")
    lines.append("")
    lines.append("Relevant recent trace kinds:")
    lines.append("")
    interesting = [
        event
        for event in events
        if str(event.get("kind", "")).endswith(
            (
                ".failed",
                ".cancelled",
                ".rejected",
                ".recovered",
                ".retried",
                "runtime.error",
                "shutdown_timeout",
                "validation.failed",
            )
        )
        or event.get("kind")
        in {
            "task.shutdown_timeout",
            "runtime.error",
            "llm.validation.failed",
            "llm.correction.started",
        }
    ]
    for event in interesting[-40:]:
        lines.append(
            f"- seq={event.get('sequence')} kind={event.get('kind')} "
            f"context={json.dumps(event.get('context') or {}, sort_keys=True)}"
        )
    lines.append("")
    lines.append("Inspect `trace.jsonl` for full evidence.")
    lines.append("")
    return "\n".join(lines)


def finalize_debug_bundle(
    recorder: DiagnosticRecorder,
    store: SQLiteStore,
    *,
    primary_exception: BaseException | None = None,
    cleanup_exception: BaseException | None = None,
) -> None:
    """Best-effort supplementary artifacts. Never raises to callers."""
    try:
        events = load_trace_events(recorder.run_dir)
        touched = extract_touched_ids(events)
        state = build_state_projection(store, touched=touched)
        write_private_text(
            recorder.run_dir / "state.json",
            json.dumps(
                sanitize_value(state, secret_values=recorder.secret_values),
                indent=2,
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            )
            + "\n",
        )
        session_ids = set(touched.get("session_id", set()))
        for session in state.get("sessions") or []:
            if isinstance(session, Mapping) and session.get("id"):
                session_ids.add(str(session["id"]))
        transcript = build_transcript_markdown(store, session_ids=session_ids)
        for secret in recorder.secret_values:
            if secret:
                transcript = transcript.replace(secret, "[REDACTED]")
        write_private_text(recorder.run_dir / "transcript.md", transcript)

        problems = classify_unresolved_problems(
            recorder=recorder,
            events=events,
            state=state,
            primary_exception=primary_exception,
            cleanup_exception=cleanup_exception,
        )
        if problems:
            summary = build_failure_summary(problems=problems, events=events)
            for secret in recorder.secret_values:
                if secret:
                    summary = summary.replace(secret, "[REDACTED]")
            write_private_text(recorder.run_dir / "failure_summary.md", summary)
    except Exception as exc:
        recorder.record(
            "runtime.error",
            {
                "phase": "debug_bundle_finalize",
                "error_type": type(exc).__name__,
                "error_message": _safe_exception_message(exc),
            },
        )
        sys.stderr.write(
            "jung diagnostics: bundle finalize failed: "
            f"{type(exc).__name__}: {_safe_exception_message(exc)}\n"
        )


def export_db_snapshot(*, run_dir: Path, database: Path) -> Path:
    run_dir = Path(run_dir)
    database = Path(database)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run directory does not exist: {run_dir}")
    if not database.is_file():
        raise FileNotFoundError(f"database does not exist: {database}")
    destination = run_dir / "db_snapshot.sqlite"
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")

    destination_created = False
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        destination_created = True
        os.close(fd)

        uri = database.resolve().as_uri() + "?mode=ro"
        source = sqlite3.connect(uri, uri=True)
        try:
            dest = sqlite3.connect(destination)
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
        try:
            os.chmod(destination, 0o600)
        except OSError:
            pass
        return destination
    except BaseException:
        if destination_created:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jung-debug-export",
        description="Export a read-only SQLite snapshot into an existing debug run.",
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        path = export_db_snapshot(run_dir=args.run_dir, database=args.database)
    except Exception as exc:
        sys.stderr.write(f"jung-debug-export: {exc}\n")
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
