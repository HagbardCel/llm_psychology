"""Journey evidence writers and mechanical forensic audit."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from jung.diagnostics import open_private_file, sanitize_url, snapshot_database
from jung.domain.session_artifacts import SessionAnalysis, SessionReview
from jung.domain.text import normalize_content
from jung.phases.context_projection import minimal_session_briefing_projection
from jung.phases.post_session.models import PostSessionUpdateResult

SimulationStatus = Literal["complete", "failed"]

_CONTEXT_DATA_RE = re.compile(
    r"<context_data>\n(?P<body>.*?)\n</context_data>",
    flags=re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class JourneyEvent:
    sequence: int
    timestamp: str
    kind: str
    context: dict[str, Any]
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AuditFinding:
    code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditResult:
    findings: list[AuditFinding] = field(default_factory=list)
    warnings: list[AuditFinding] = field(default_factory=list)
    not_applicable: list[AuditFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def fail(self, code: str, message: str, **evidence: Any) -> None:
        self.findings.append(
            AuditFinding(code=code, message=message, evidence=evidence)
        )

    def warn(self, code: str, message: str, **evidence: Any) -> None:
        self.warnings.append(
            AuditFinding(code=code, message=message, evidence=evidence)
        )

    def na(self, code: str, message: str, **evidence: Any) -> None:
        self.not_applicable.append(
            AuditFinding(code=code, message=message, evidence=evidence)
        )


@dataclass(frozen=True, slots=True)
class SupervisorCallReconstruction:
    llm_call_id: str
    model: str | None
    accepted_result: Mapping[str, Any]
    accepted_sequence: int


class JourneyLog:
    """Append-only journey.jsonl with fixed five-field envelope."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._sequence = 0
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            with open_private_file(self._path, mode="w"):
                pass

    def append(
        self,
        kind: str,
        *,
        context: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> JourneyEvent:
        self._sequence += 1
        event = JourneyEvent(
            sequence=self._sequence,
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            kind=kind,
            context=dict(context or {}),
            data=dict(data or {}),
        )
        line = json.dumps(
            {
                "sequence": event.sequence,
                "timestamp": event.timestamp,
                "kind": event.kind,
                "context": event.context,
                "data": event.data,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with open_private_file(self._path, mode="a") as handle:
            handle.write(line + "\n")
        return event


def allocate_run_directory(output_dir: Path | None = None) -> Path:
    """Create an exclusive run directory with private permissions."""
    if output_dir is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_dir = Path("logs") / "simulations" / f"run-{stamp}"
    run_dir = Path(output_dir)
    if run_dir.exists():
        raise FileExistsError(f"simulation output directory already exists: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        os.chmod(run_dir, 0o700)
    except OSError:
        pass
    data_dir = run_dir / "data"
    data_dir.mkdir(mode=0o700)
    try:
        os.chmod(data_dir, 0o700)
    except OSError:
        pass
    checkpoints = run_dir / "checkpoints"
    checkpoints.mkdir(mode=0o700)
    try:
        os.chmod(checkpoints, 0o700)
    except OSError:
        pass
    return run_dir


def create_checkpoint(source_db: Path, destination: Path) -> None:
    snapshot_database(source_db, destination)


def git_provenance() -> tuple[str | None, bool | None]:
    """Best-effort git commit and dirty-worktree flags."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None, None
    try:
        dirty_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
        dirty = bool(dirty_proc.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return commit or None, None
    return commit or None, dirty


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def extract_context_data(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Strictly parse exactly one <context_data> block from user messages."""
    user_messages = [
        message
        for message in messages
        if isinstance(message, Mapping)
        and message.get("role") == "user"
        and isinstance(message.get("content"), str)
    ]
    matches: list[re.Match[str]] = []
    for message in user_messages:
        content = str(message["content"])
        found = list(_CONTEXT_DATA_RE.finditer(content))
        if not found:
            continue
        if len(found) != 1:
            raise ValueError("multiple <context_data> blocks in one user message")
        match = found[0]
        trailing = content[match.end() :].strip()
        if "<context_data>" in trailing or "</context_data>" in trailing:
            raise ValueError("ambiguous trailing <context_data> content")
        matches.append(match)
    if not matches:
        raise ValueError("no <context_data> block found")
    if len(matches) != 1:
        raise ValueError("multiple user messages contain <context_data>")
    return json.loads(matches[0].group("body"))


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_section(audit: AuditResult, code: str, section: str) -> Any:
    """Context-manager-like helper: run callable and convert escapes to findings."""

    class _Guard:
        def __enter__(self) -> AuditResult:
            return audit

        def __exit__(self, exc_type: Any, exc: Any, _tb: Any) -> bool:
            if exc_type is None:
                return False
            if issubclass(exc_type, Exception):
                audit.fail(
                    "audit_section_error",
                    f"{section}: {type(exc).__name__}: {exc}",
                    section=section,
                    code_hint=code,
                )
                return True
            return False

    return _Guard()


def check_sqlite_integrity(db_path: Path, audit: AuditResult) -> None:
    if not db_path.is_file():
        audit.fail(
            "missing_database",
            f"database missing: {db_path}",
            path=str(db_path),
        )
        return
    conn = _connect_readonly(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            audit.fail(
                "sqlite_integrity",
                f"integrity_check={integrity!r}",
                path=str(db_path),
            )
        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            audit.fail(
                "sqlite_foreign_keys",
                f"foreign_key_check returned {len(fk_rows)} row(s)",
                path=str(db_path),
            )
    finally:
        conn.close()


def _session_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT id, kind, plan_id, started_at, ended_at, review_json "
            "FROM sessions ORDER BY started_at, id"
        )
    )


def audit_therapy_session_messages(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    submitted_turns: Sequence[Mapping[str, Any]],
    audit: AuditResult,
) -> None:
    row = conn.execute(
        "SELECT id, kind FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        audit.fail("missing_session", "therapy session missing", session_id=session_id)
        return
    if row["kind"] != "therapy":
        audit.fail(
            "session_kind",
            f"expected therapy, got {row['kind']!r}",
            session_id=session_id,
        )

    for turn in submitted_turns:
        client_message_id = str(turn["client_message_id"])
        user_rows = conn.execute(
            "SELECT id, content, sequence FROM messages "
            "WHERE session_id = ? AND client_message_id = ? AND role = 'user'",
            (session_id, client_message_id),
        ).fetchall()
        if len(user_rows) != 1:
            audit.fail(
                "missing_user_message",
                f"expected one user message for client_message_id={client_message_id}",
                session_id=session_id,
                client_message_id=client_message_id,
                count=len(user_rows),
            )
            continue
        if user_rows[0]["content"] != turn["patient_text"]:
            audit.fail(
                "user_content_mismatch",
                "durable user content != submitted patient text",
                session_id=session_id,
                client_message_id=client_message_id,
            )
        assistant_rows = conn.execute(
            "SELECT id, content, sequence FROM messages "
            "WHERE session_id = ? AND client_message_id = ? AND role = 'assistant'",
            (session_id, client_message_id),
        ).fetchall()
        if len(assistant_rows) != 1:
            audit.fail(
                "missing_assistant_message",
                "expected one assistant message",
                session_id=session_id,
                client_message_id=client_message_id,
                count=len(assistant_rows),
            )
            continue
        if assistant_rows[0]["content"] != turn["assistant_text"]:
            audit.fail(
                "assistant_content_mismatch",
                "durable assistant content != streamed text",
                session_id=session_id,
                client_message_id=client_message_id,
            )
        if assistant_rows[0]["sequence"] != user_rows[0]["sequence"] + 1:
            audit.fail(
                "message_sequence",
                "assistant sequence must follow user sequence",
                session_id=session_id,
                client_message_id=client_message_id,
            )


def audit_completed_therapy_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    submitted_turns: Sequence[Mapping[str, Any]],
    audit: AuditResult,
) -> SessionReview | None:
    del submitted_turns
    row = conn.execute(
        "SELECT id, kind, ended_at, review_json FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    if row["ended_at"] is None:
        audit.fail("session_not_ended", "ended_at is NULL", session_id=session_id)
    if row["review_json"] is None:
        audit.fail("missing_review", "review_json is NULL", session_id=session_id)
        review = None
    else:
        try:
            review = SessionReview.model_validate_json(row["review_json"])
        except Exception as exc:
            audit.fail(
                "invalid_review",
                f"review_json did not validate: {exc}",
                session_id=session_id,
            )
            review = None

    ops = conn.execute(
        "SELECT id, status FROM operations "
        "WHERE kind = 'post_session' AND source_session_id = ?",
        (session_id,),
    ).fetchall()
    if len(ops) != 1:
        audit.fail(
            "post_session_operation_count",
            f"expected exactly one post_session operation, got {len(ops)}",
            session_id=session_id,
        )
    elif ops[0]["status"] != "complete":
        audit.fail(
            "post_session_incomplete",
            f"operation status={ops[0]['status']!r}",
            session_id=session_id,
            operation_id=ops[0]["id"],
        )
    return review


def _event_task(event: Mapping[str, Any]) -> str | None:
    data = event.get("data") or {}
    context = event.get("context") or {}
    task = data.get("task") or context.get("llm_task")
    return str(task) if task is not None else None


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
    raise ValueError(f"trace event missing integer sequence: {event.get('kind')!r}")


def reconstruct_supervisor_call(
    events: Sequence[Mapping[str, Any]],
    *,
    task: str,
    session_id: str | None = None,
) -> tuple[SupervisorCallReconstruction | None, list[str]]:
    """Reconstruct one structured supervisor call by llm_call_id correlation."""
    errors: list[str] = []
    scoped = [
        event
        for event in events
        if _event_task(event) == task
        and (
            session_id is None
            or (event.get("context") or {}).get("session_id") == session_id
        )
    ]
    logical_kinds = {
        "llm.provider.request",
        "llm.provider.response",
        "llm.provider.error",
        "llm.output.accepted",
    }
    logical_events = [event for event in scoped if event.get("kind") in logical_kinds]
    if any(_event_llm_call_id(event) is None for event in logical_events):
        errors.append(f"{task}: provider/accepted event missing llm_call_id")
        return None, errors
    call_ids = {_event_llm_call_id(event) for event in logical_events}
    if len(call_ids) != 1:
        errors.append(
            f"{task}: expected exactly one llm_call_id, got {sorted(call_ids)!r}"
        )
        return None, errors
    llm_call_id = next(iter(call_ids))
    assert llm_call_id is not None
    call_events = [
        event for event in logical_events if _event_llm_call_id(event) == llm_call_id
    ]

    accepted = [
        event for event in call_events if event.get("kind") == "llm.output.accepted"
    ]
    if len(accepted) != 1:
        errors.append(
            f"{task}: expected exactly one llm.output.accepted, got {len(accepted)}"
        )
        return None, errors
    accepted_event = accepted[0]
    accepted_sequence = _event_sequence(accepted_event)
    result = (accepted_event.get("data") or {}).get("result")
    if not isinstance(result, Mapping):
        errors.append(f"{task}: accepted result is not a mapping")
        return None, errors

    requests_by_attempt: dict[str, list[dict[str, Any]]] = {}
    terminals_by_attempt: dict[str, list[dict[str, Any]]] = {}
    for event in call_events:
        kind = event.get("kind")
        if kind == "llm.provider.request":
            attempt_id = _event_provider_attempt_id(event)
            if attempt_id is None:
                errors.append(f"{task}: provider request missing provider_attempt_id")
                continue
            requests_by_attempt.setdefault(attempt_id, []).append(dict(event))
        elif kind in {"llm.provider.response", "llm.provider.error"}:
            attempt_id = _event_provider_attempt_id(event)
            if attempt_id is None:
                errors.append(
                    f"{task}: terminal provider event missing provider_attempt_id"
                )
                continue
            terminals_by_attempt.setdefault(attempt_id, []).append(dict(event))

    attempt_ids = set(requests_by_attempt) | set(terminals_by_attempt)
    if not attempt_ids:
        errors.append(f"{task}: missing provider request(s)")
        return None, errors

    models: set[str] = set()
    success_count = 0
    for attempt_id in sorted(attempt_ids):
        requests = requests_by_attempt.get(attempt_id, [])
        terminals = terminals_by_attempt.get(attempt_id, [])
        if len(requests) != 1 or len(terminals) != 1:
            errors.append(
                f"{task}: provider_attempt_id={attempt_id!r} expected exactly one "
                f"request and one terminal, got requests={len(requests)} "
                f"terminals={len(terminals)}"
            )
            continue
        request = requests[0]
        terminal = terminals[0]
        request_sequence = _event_sequence(request)
        terminal_sequence = _event_sequence(terminal)
        if not (request_sequence < terminal_sequence < accepted_sequence):
            errors.append(
                f"{task}: provider_attempt_id={attempt_id!r} requires "
                f"request.sequence < terminal.sequence < accepted.sequence "
                f"(got {request_sequence} < {terminal_sequence} < {accepted_sequence})"
            )
        request_model = (request.get("data") or {}).get("model")
        if not isinstance(request_model, str) or not request_model.strip():
            errors.append(
                f"{task}: provider request missing non-empty model "
                f"(provider_attempt_id={attempt_id!r})"
            )
        else:
            models.add(request_model)
        if (
            terminal.get("kind") == "llm.provider.response"
            and (terminal.get("data") or {}).get("status") == "success"
        ):
            success_count += 1

    if success_count < 1:
        errors.append(f"{task}: no successful provider.response")
    if len(models) != 1:
        errors.append(
            f"{task}: expected exactly one request model across attempts, "
            f"got {sorted(models)!r}"
        )
        model: str | None = None
    else:
        model = next(iter(models))

    if errors:
        return None, errors

    return (
        SupervisorCallReconstruction(
            llm_call_id=llm_call_id,
            model=model,
            accepted_result=result,
            accepted_sequence=accepted_sequence,
        ),
        [],
    )


def audit_supervisor_session(
    events: Sequence[Mapping[str, Any]],
    *,
    session_id: str | None,
    review: SessionReview | None,
) -> list[str]:
    """Validate analysis+update chains and durable SessionReview composition."""
    errors: list[str] = []
    analysis, analysis_errors = reconstruct_supervisor_call(
        events, task="post_session_analysis", session_id=session_id
    )
    errors.extend(analysis_errors)
    update, update_errors = reconstruct_supervisor_call(
        events, task="post_session_update", session_id=session_id
    )
    errors.extend(update_errors)

    accepted_analysis: SessionAnalysis | None = None
    if analysis is not None:
        try:
            accepted_analysis = SessionAnalysis.model_validate(analysis.accepted_result)
        except Exception as exc:
            errors.append(f"post_session_analysis: accepted result invalid: {exc}")

    accepted_update: PostSessionUpdateResult | None = None
    if update is not None:
        try:
            accepted_update = PostSessionUpdateResult.model_validate(
                update.accepted_result
            )
        except Exception as exc:
            errors.append(f"post_session_update: accepted result invalid: {exc}")

    if review is None:
        return errors

    if accepted_analysis is not None and accepted_analysis != review.analysis:
        errors.append("accepted SessionAnalysis != durable review.analysis")
    if accepted_update is not None:
        if accepted_update.session_briefing != review.briefing:
            errors.append(
                "accepted PostSessionUpdateResult.session_briefing "
                "!= durable review.briefing"
            )
        if accepted_update.plan_patch != review.plan_recommendation:
            errors.append(
                "accepted PostSessionUpdateResult.plan_patch "
                "!= durable review.plan_recommendation"
            )

    if review.generation is None:
        errors.append("durable review.generation is null")
    else:
        if analysis is not None and analysis.model is not None:
            if review.generation.analysis_model != analysis.model:
                errors.append(
                    "review.generation.analysis_model != reconstructed analysis model"
                )
        if update is not None and update.model is not None:
            if review.generation.update_model != update.model:
                errors.append(
                    "review.generation.update_model != reconstructed update model"
                )
    return errors


def audit_supervisor_chain_from_fixture(
    events: Sequence[Mapping[str, Any]],
    *,
    review: SessionReview | None = None,
    session_id: str | None = None,
) -> list[str]:
    """Validate the forensic supervisor sequence against a fixture trace."""
    return audit_supervisor_session(events, session_id=session_id, review=review)


def audit_grounding(conn: sqlite3.Connection, audit: AuditResult) -> None:
    rows = conn.execute(
        "SELECT g.message_id, m.role, m.session_id, m.sequence, m.content "
        "FROM grounded_patient_turns g "
        "LEFT JOIN messages m ON m.id = g.message_id"
    ).fetchall()
    for row in rows:
        if row["role"] is None:
            audit.fail(
                "grounding_missing_message",
                "grounded message_id has no messages row",
                message_id=row["message_id"],
            )
            continue
        if row["role"] != "user":
            audit.fail(
                "grounding_role",
                f"grounded message role={row['role']!r}",
                message_id=row["message_id"],
            )

    sessions = conn.execute(
        "SELECT id, review_json FROM sessions "
        "WHERE kind = 'therapy' AND review_json IS NOT NULL"
    ).fetchall()
    for session in sessions:
        session_id = session["id"]
        try:
            review = SessionReview.model_validate_json(session["review_json"])
        except Exception as exc:
            audit.fail(
                "invalid_review",
                f"review_json did not validate during grounding: {exc}",
                session_id=session_id,
            )
            continue
        expected_ids: set[str] = set()
        for citation in review.analysis.patient_turn_citations:
            matches = conn.execute(
                "SELECT id FROM messages "
                "WHERE session_id = ? AND sequence = ? AND role = 'user'",
                (session_id, citation.patient_sequence),
            ).fetchall()
            if len(matches) != 1:
                audit.fail(
                    "grounding_citation_unresolved",
                    "patient_turn_citation did not resolve to exactly one user message",
                    session_id=session_id,
                    patient_sequence=citation.patient_sequence,
                    count=len(matches),
                )
                continue
            expected_ids.add(matches[0]["id"])
        actual_ids = {
            row["message_id"]
            for row in conn.execute(
                "SELECT g.message_id FROM grounded_patient_turns g "
                "JOIN messages m ON m.id = g.message_id "
                "WHERE m.session_id = ?",
                (session_id,),
            ).fetchall()
        }
        if expected_ids != actual_ids:
            audit.fail(
                "grounding_set_mismatch",
                "citation-derived message IDs != grounded_patient_turns for session",
                session_id=session_id,
                expected=sorted(expected_ids),
                actual=sorted(actual_ids),
            )


def audit_plan_lineage(conn: sqlite3.Connection, audit: AuditResult) -> None:
    plans = list(
        conn.execute(
            "SELECT id, version, source_session_id, supersedes_plan_id "
            "FROM plans ORDER BY version"
        )
    )
    profile = conn.execute("SELECT current_plan_id FROM profile").fetchone()
    if not plans:
        return
    if profile is None or profile["current_plan_id"] is None:
        audit.fail("missing_current_plan", "profile.current_plan_id is NULL")
    else:
        current_ids = {plan["id"] for plan in plans}
        if profile["current_plan_id"] not in current_ids:
            audit.fail(
                "current_plan_missing",
                "profile.current_plan_id not in plans",
                current_plan_id=profile["current_plan_id"],
            )
        elif profile["current_plan_id"] != plans[-1]["id"]:
            audit.fail(
                "current_plan_not_latest",
                "profile.current_plan_id is not the latest plan version",
                current_plan_id=profile["current_plan_id"],
                latest_plan_id=plans[-1]["id"],
            )

    previous_id: str | None = None
    previous_version = 0
    for plan in plans:
        if plan["version"] != previous_version + 1:
            audit.fail(
                "plan_version",
                f"expected version {previous_version + 1}, got {plan['version']}",
                plan_id=plan["id"],
            )
        if previous_id is None:
            if plan["supersedes_plan_id"] is not None:
                audit.fail(
                    "plan_supersedes",
                    "first plan must not supersede another plan",
                    plan_id=plan["id"],
                )
        else:
            if plan["source_session_id"] is None:
                audit.fail(
                    "plan_source_session",
                    "revision missing source_session_id",
                    plan_id=plan["id"],
                )
            else:
                session = conn.execute(
                    "SELECT kind, ended_at, review_json FROM sessions WHERE id = ?",
                    (plan["source_session_id"],),
                ).fetchone()
                if session is None:
                    audit.fail(
                        "plan_source_missing",
                        "source session missing",
                        plan_id=plan["id"],
                        source_session_id=plan["source_session_id"],
                    )
                else:
                    if session["kind"] != "therapy" or session["ended_at"] is None:
                        audit.fail(
                            "plan_source_not_ended_therapy",
                            "source session is not an ended therapy session",
                            plan_id=plan["id"],
                            source_session_id=plan["source_session_id"],
                        )
                    if session["review_json"] is None:
                        audit.fail(
                            "plan_source_without_review",
                            "source session has no review_json",
                            plan_id=plan["id"],
                            source_session_id=plan["source_session_id"],
                        )
            if plan["supersedes_plan_id"] != previous_id:
                audit.fail(
                    "plan_supersedes_mismatch",
                    "supersedes_plan_id must be previous current plan",
                    plan_id=plan["id"],
                    expected=previous_id,
                    actual=plan["supersedes_plan_id"],
                )
        previous_id = plan["id"]
        previous_version = plan["version"]


def find_provider_requests(
    trace: Sequence[Mapping[str, Any]],
    *,
    task: str,
    session_id: str | None = None,
    client_message_id: str | None = None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for event in trace:
        if event.get("kind") != "llm.provider.request":
            continue
        if _event_task(event) != task:
            continue
        context = event.get("context") or {}
        if session_id is not None and context.get("session_id") != session_id:
            continue
        if (
            client_message_id is not None
            and context.get("client_message_id") != client_message_id
        ):
            continue
        matches.append(dict(event))
    return matches


def find_accepted_outputs(
    trace: Sequence[Mapping[str, Any]],
    *,
    task: str,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for event in trace:
        if event.get("kind") != "llm.output.accepted":
            continue
        if _event_task(event) != task:
            continue
        context = event.get("context") or {}
        if session_id is not None and context.get("session_id") != session_id:
            continue
        matches.append(dict(event))
    return matches


def compare_briefing_projection(
    review: SessionReview,
    projected: Mapping[str, Any] | None,
) -> list[str]:
    errors: list[str] = []
    expected = minimal_session_briefing_projection(review.briefing)
    if projected is None:
        return ["latest_supervisor_briefing missing from therapy context"]
    for key in ("narrative_handoff", "recommended_opening_focus"):
        if projected.get(key) != expected[key]:
            errors.append(
                f"{key} mismatch: prompt={projected.get(key)!r} "
                f"expected={expected[key]!r}"
            )
    return errors


def render_transcript_from_snapshot(db_path: Path) -> str:
    conn = _connect_readonly(db_path)
    try:
        lines = ["# Simulation transcript", ""]
        sessions = _session_rows(conn)
        therapy_index = 0
        for session in sessions:
            messages = conn.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id = ? ORDER BY sequence",
                (session["id"],),
            ).fetchall()
            if session["kind"] == "intake":
                lines.append("## Intake")
                lines.append("")
            else:
                therapy_index += 1
                lines.append(f"## Therapy session {therapy_index}")
                lines.append("")
            for message in messages:
                speaker = "Patient" if message["role"] == "user" else "Therapist"
                lines.append(f"{speaker}:")
                lines.append(message["content"])
                lines.append("")
        return "\n".join(lines).rstrip() + "\n"
    finally:
        conn.close()


def write_private_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_private_file(path, mode="w") as handle:
        handle.write(text)


def write_run_json(path: Path, payload: Mapping[str, Any]) -> None:
    write_private_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
    )


def scenario_snapshot(scenario: Any) -> dict[str, Any]:
    return asdict(scenario)


def format_diagnostic_capture_status(status: str | None) -> str:
    if status == "success":
        return "COMPLETE"
    if status == "failed":
        return "FAILED"
    if status is None:
        return "UNKNOWN"
    return status.upper()


def render_audit_markdown(
    *,
    status: SimulationStatus,
    runtime_diagnostics_status: str | None,
    findings: Sequence[AuditFinding],
    warnings: Sequence[AuditFinding],
    not_applicable: Sequence[AuditFinding],
    run_config: Mapping[str, Any],
    artifact_index: Sequence[str],
    journey_error_code: str | None = None,
    journey_error_message: str | None = None,
    journey_api_error: Mapping[str, Any] | None = None,
) -> str:
    lines = [
        "# Journey Audit",
        "",
        "## Run configuration",
        "",
        "```json",
        json.dumps(dict(run_config), indent=2, default=str),
        "```",
        "",
        "## Simulation result",
        "",
        f"Simulation result: {status.upper()}",
        f"Diagnostic capture: {format_diagnostic_capture_status(runtime_diagnostics_status)}",
    ]
    if run_config.get("git_worktree_dirty") is True:
        lines.append(
            "WARNING: source worktree was dirty; exact executed source is not "
            "reproducible from git_commit alone."
        )
    if journey_error_code is not None or journey_error_message is not None:
        lines.extend(
            [
                "",
                "## Journey failure",
                "",
                f"error_code: `{journey_error_code or 'unknown'}`",
                f"error_message: {journey_error_message or ''}",
            ]
        )
        if journey_api_error is not None:
            lines.extend(
                [
                    "",
                    "api_error:",
                    "",
                    "```json",
                    json.dumps(dict(journey_api_error), indent=2, default=str),
                    "```",
                ]
            )
    lines.extend(
        [
            "",
            "## Mechanical failures",
            "",
        ]
    )
    if findings:
        for finding in findings:
            lines.append(f"- `{finding.code}`: {finding.message}")
            if finding.evidence:
                evidence_json = json.dumps(finding.evidence, default=str)
                lines.append(f"  evidence: `{evidence_json}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        for warning in warnings:
            lines.append(f"- `{warning.code}`: {warning.message}")
    else:
        lines.append("- none")
    lines.extend(["", "## Not applicable", ""])
    if not_applicable:
        for item in not_applicable:
            lines.append(f"- `{item.code}`: {item.message}")
            if item.evidence:
                evidence_json = json.dumps(item.evidence, default=str)
                lines.append(f"  evidence: `{evidence_json}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Artifact index", ""])
    for item in artifact_index:
        lines.append(f"- `{item}`")
    lines.append("")
    return "\n".join(lines)


def _durable_db_for_session(
    *,
    snapshot: Path | None,
    checkpoints_dir: Path,
    session_number: int,
) -> Path | None:
    if snapshot is not None and snapshot.is_file():
        return snapshot
    checkpoint = checkpoints_dir / f"after-session-{session_number:03d}.sqlite"
    if checkpoint.is_file():
        return checkpoint
    return None


def _newest_session_checkpoint(
    checkpoints_dir: Path,
    max_session_number: int,
) -> Path | None:
    for number in range(max_session_number, 0, -1):
        candidate = checkpoints_dir / f"after-session-{number:03d}.sqlite"
        if candidate.is_file():
            return candidate
    return None


def _audit_checkpoints(
    audit: AuditResult,
    checkpoints_dir: Path,
    *,
    initial_ready_reached: bool,
) -> None:
    with _safe_section(audit, "checkpoints", "checkpoints"):
        initial = checkpoints_dir / "initial-ready.sqlite"
        if not initial_ready_reached:
            audit.na("initial_ready_checkpoint", "run never reached READY")
            return
        if initial.is_file():
            check_sqlite_integrity(initial, audit)
        else:
            audit.fail("missing_initial_checkpoint", "initial-ready.sqlite missing")


def _audit_final_database(
    *,
    audit: AuditResult,
    snapshot: Path | None,
    checkpoints_dir: Path,
    therapy_sessions: Sequence[Mapping[str, Any]],
) -> Path | None:
    resolved: Path | None = None
    if snapshot is not None and snapshot.is_file():
        resolved = snapshot
    if resolved is None:
        audit.fail("missing_final_snapshot", "runtime/db_snapshot.sqlite missing")
    else:
        with _safe_section(audit, "final_snapshot", "final_snapshot"):
            check_sqlite_integrity(resolved, audit)

    for index, session_info in enumerate(therapy_sessions, start=1):
        post_session_entered = bool(session_info.get("post_session_entered"))
        with _safe_section(audit, "session_durable", f"session_durable:{index}"):
            checkpoint = checkpoints_dir / f"after-session-{index:03d}.sqlite"
            if post_session_entered:
                if checkpoint.is_file():
                    check_sqlite_integrity(checkpoint, audit)
                else:
                    audit.fail(
                        "missing_session_checkpoint",
                        f"missing {checkpoint.name}",
                        session_number=index,
                    )
            else:
                audit.na(
                    "session_checkpoint",
                    "post-session was not entered",
                    session_number=index,
                )
            durable = _durable_db_for_session(
                snapshot=resolved,
                checkpoints_dir=checkpoints_dir,
                session_number=index,
            )
            if durable is None:
                if list(session_info.get("turns") or ()):
                    audit.fail(
                        "missing_session_durable_evidence",
                        "no final snapshot or session checkpoint for durable checks",
                        session_id=str(session_info["session_id"]),
                        session_number=index,
                    )
                continue
            conn = _connect_readonly(durable)
            try:
                submitted_turns = list(session_info.get("turns") or ())
                audit_therapy_session_messages(
                    conn,
                    session_id=str(session_info["session_id"]),
                    submitted_turns=submitted_turns,
                    audit=audit,
                )
                if post_session_entered:
                    audit_completed_therapy_session(
                        conn,
                        session_id=str(session_info["session_id"]),
                        submitted_turns=submitted_turns,
                        audit=audit,
                    )
                else:
                    audit.na(
                        "session_completion",
                        "post-session was not entered",
                        session_number=index,
                    )
            finally:
                conn.close()

    lineage_db = resolved
    if lineage_db is None and therapy_sessions:
        lineage_db = _newest_session_checkpoint(
            checkpoints_dir,
            len(therapy_sessions),
        )
    if lineage_db is not None and lineage_db.is_file():
        conn = _connect_readonly(lineage_db)
        try:
            with _safe_section(audit, "grounding", "grounding"):
                audit_grounding(conn, audit)
            with _safe_section(audit, "plan_lineage", "plan_lineage"):
                audit_plan_lineage(conn, audit)
        finally:
            conn.close()
    return resolved


def run_mechanical_audit(
    *,
    run_dir: Path,
    provider_trace_required: bool,
    configured_sessions: int,
    therapy_sessions: Sequence[Mapping[str, Any]],
    initial_ready_reached: bool,
) -> AuditResult:
    """Collect forensic findings from checkpoints, final snapshot, and trace."""
    audit = AuditResult()
    checkpoints_dir = run_dir / "checkpoints"
    _audit_checkpoints(
        audit,
        checkpoints_dir,
        initial_ready_reached=initial_ready_reached,
    )

    snapshot_path = run_dir / "runtime" / "db_snapshot.sqlite"
    snapshot = _audit_final_database(
        audit=audit,
        snapshot=snapshot_path if snapshot_path.is_file() else None,
        checkpoints_dir=checkpoints_dir,
        therapy_sessions=therapy_sessions,
    )

    with _safe_section(audit, "provider_trace", "provider_trace"):
        trace_path = run_dir / "runtime" / "trace.jsonl"
        trace = load_jsonl(trace_path)
        if provider_trace_required:
            if not any(event.get("kind") == "llm.provider.request" for event in trace):
                audit.fail(
                    "missing_provider_trace",
                    "provider_trace_required but no llm.provider.request events found",
                )
            else:
                _audit_provider_prompt_chains(
                    audit=audit,
                    trace=trace,
                    configured_sessions=configured_sessions,
                    therapy_sessions=therapy_sessions,
                    snapshot=snapshot,
                    checkpoints_dir=checkpoints_dir,
                )
        elif not any(event.get("kind") == "llm.provider.request" for event in trace):
            audit.warn(
                "provider_trace_unavailable",
                "llm.provider.request events absent (expected under FakeLLM)",
            )
    return audit


def _load_review(
    conn: sqlite3.Connection,
    session_id: str,
) -> SessionReview | None:
    row = conn.execute(
        "SELECT review_json FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None or row["review_json"] is None:
        return None
    return SessionReview.model_validate_json(row["review_json"])


def _audit_supervisor_session(
    *,
    audit: AuditResult,
    trace: Sequence[Mapping[str, Any]],
    session_id: str,
    review: SessionReview | None,
) -> None:
    for error in audit_supervisor_session(trace, session_id=session_id, review=review):
        audit.fail(
            "supervisor_chain",
            error,
            session_id=session_id,
        )


def _audit_provider_call(
    *,
    audit: AuditResult,
    trace: Sequence[Mapping[str, Any]],
    session_id: str,
    client_message_id: str,
    patient_text: str,
    conn: sqlite3.Connection | None,
) -> None:
    requests = find_provider_requests(
        trace,
        task="therapy_response",
        session_id=session_id,
        client_message_id=client_message_id,
    )
    if not requests:
        audit.fail(
            "missing_therapy_request",
            "therapy_response provider request missing",
            session_id=session_id,
            client_message_id=client_message_id,
        )
        return
    try:
        document = extract_context_data(
            (requests[0].get("data") or {}).get("messages") or ()
        )
    except ValueError as exc:
        audit.fail(
            "malformed_context_data",
            str(exc),
            session_id=session_id,
            client_message_id=client_message_id,
        )
        return
    current = document.get("current_patient_message")
    if current != patient_text:
        audit.fail(
            "patient_message_prompt_mismatch",
            "current_patient_message != durable/submitted patient text",
            session_id=session_id,
            client_message_id=client_message_id,
        )
    if conn is None:
        return
    historical = document.get("historical_context")
    if isinstance(historical, Mapping):
        grounded = historical.get("grounded_patient_turns")
        if isinstance(grounded, list):
            _audit_grounded_prompt_contents(conn, grounded, audit=audit)


def _audit_provider_prompt_chains(
    *,
    audit: AuditResult,
    trace: Sequence[Mapping[str, Any]],
    configured_sessions: int,
    therapy_sessions: Sequence[Mapping[str, Any]],
    snapshot: Path | None,
    checkpoints_dir: Path,
) -> None:
    for index, session_info in enumerate(therapy_sessions, start=1):
        post_session_entered = bool(session_info.get("post_session_entered"))
        session_id = str(session_info["session_id"])
        durable = _durable_db_for_session(
            snapshot=snapshot,
            checkpoints_dir=checkpoints_dir,
            session_number=index,
        )
        review: SessionReview | None = None
        conn: sqlite3.Connection | None = None
        try:
            if durable is not None:
                conn = _connect_readonly(durable)
                if post_session_entered:
                    try:
                        review = _load_review(conn, session_id)
                    except Exception as exc:
                        audit.fail(
                            "invalid_review",
                            f"review_json did not validate: {exc}",
                            session_id=session_id,
                        )
                        review = None

            for turn in session_info.get("turns") or ():
                with _safe_section(
                    audit,
                    "therapy_prompt",
                    f"therapy_prompt:{session_id}:{turn['client_message_id']}",
                ):
                    _audit_provider_call(
                        audit=audit,
                        trace=trace,
                        session_id=session_id,
                        client_message_id=str(turn["client_message_id"]),
                        patient_text=str(turn["patient_text"]),
                        conn=conn,
                    )

            if post_session_entered:
                with _safe_section(audit, "supervisor", f"supervisor:{session_id}"):
                    _audit_supervisor_session(
                        audit=audit,
                        trace=trace,
                        session_id=session_id,
                        review=review,
                    )
            else:
                audit.na(
                    "supervisor_chain",
                    "post-session was not entered",
                    session_id=session_id,
                    session_number=index,
                )

            if index >= configured_sessions or index >= len(therapy_sessions):
                continue
            next_session = therapy_sessions[index]
            next_turns = list(next_session.get("turns") or ())
            if not next_turns:
                continue
            if not post_session_entered:
                audit.na(
                    "next_session_handoff",
                    "post-session was not entered",
                    source_session_id=session_id,
                    session_number=index,
                )
                continue
            first = next_turns[0]
            next_requests = find_provider_requests(
                trace,
                task="therapy_response",
                session_id=str(next_session["session_id"]),
                client_message_id=str(first["client_message_id"]),
            )
            if review is None:
                audit.fail(
                    "missing_review_for_handoff",
                    "cannot verify next-session briefing without review",
                    session_id=session_id,
                )
                continue
            if not next_requests:
                audit.fail(
                    "missing_next_session_prompt",
                    "first therapy_response of next session missing",
                    source_session_id=session_id,
                    next_session_id=str(next_session["session_id"]),
                )
                continue
            try:
                document = extract_context_data(
                    (next_requests[0].get("data") or {}).get("messages") or ()
                )
            except ValueError as exc:
                audit.fail(
                    "malformed_next_context_data",
                    str(exc),
                    source_session_id=session_id,
                )
                continue
            historical = document.get("historical_context")
            projected = None
            if isinstance(historical, Mapping):
                raw = historical.get("latest_supervisor_briefing")
                projected = dict(raw) if isinstance(raw, Mapping) else None
            for error in compare_briefing_projection(review, projected):
                audit.fail(
                    "stale_or_missing_briefing",
                    error,
                    source_session_id=session_id,
                    next_session_id=str(next_session["session_id"]),
                )
        finally:
            if conn is not None:
                conn.close()


def _audit_grounded_prompt_contents(
    conn: sqlite3.Connection,
    grounded_contents: Sequence[Any],
    *,
    audit: AuditResult,
) -> None:
    rows = conn.execute(
        "SELECT m.id, m.content FROM grounded_patient_turns g "
        "JOIN messages m ON m.id = g.message_id"
    ).fetchall()
    by_content: dict[str, list[str]] = {}
    for row in rows:
        key = normalize_content(row["content"])
        by_content.setdefault(key, []).append(row["id"])
    for item in grounded_contents:
        content = item if isinstance(item, str) else None
        if isinstance(item, Mapping):
            raw = item.get("content")
            content = raw if isinstance(raw, str) else None
        if content is None:
            audit.fail(
                "grounded_prompt_shape",
                "grounded_patient_turns item missing content",
            )
            continue
        candidates = by_content.get(normalize_content(content), [])
        if not candidates:
            audit.fail(
                "grounded_prompt_unmatched",
                "prompt grounded content not found in grounded messages",
            )
        elif len(candidates) > 1:
            audit.warn(
                "grounded_prompt_ambiguous",
                "multiple grounded message candidates share identical content",
                candidates=candidates,
            )


def diagnostics_end_status(trace: Sequence[Mapping[str, Any]]) -> str | None:
    for event in reversed(list(trace)):
        if event.get("kind") == "diagnostics.end":
            data = event.get("data") or {}
            status = data.get("status")
            return str(status) if status is not None else None
    return None


def sanitized_endpoint(url: str) -> str:
    return sanitize_url(url)


def artifact_relative_paths(run_dir: Path) -> list[str]:
    paths: list[str] = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file():
            paths.append(str(path.relative_to(run_dir)))
    return paths


def uuid_str(value: UUID | str) -> str:
    return str(value)
