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
from jung.domain.session_artifacts import SessionReview
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
        # Task text after the block is expected; additional tags are not.
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


def audit_completed_therapy_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    submitted_turns: Sequence[Mapping[str, Any]],
    audit: AuditResult,
) -> SessionReview | None:
    row = conn.execute(
        "SELECT id, kind, ended_at, review_json FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        audit.fail("missing_session", "therapy session missing", session_id=session_id)
        return None
    if row["kind"] != "therapy":
        audit.fail(
            "session_kind",
            f"expected therapy, got {row['kind']!r}",
            session_id=session_id,
        )
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
    return review


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
        review_row = conn.execute(
            "SELECT review_json FROM sessions WHERE id = ?",
            (row["session_id"],),
        ).fetchone()
        if review_row is None or review_row["review_json"] is None:
            continue
        try:
            review = SessionReview.model_validate_json(review_row["review_json"])
        except Exception:
            continue
        sequences = {
            citation.patient_sequence
            for citation in review.analysis.patient_turn_citations
        }
        if row["sequence"] not in sequences:
            audit.warn(
                "grounding_citation_mismatch",
                "grounded message sequence not listed in source review citations",
                message_id=row["message_id"],
                session_id=row["session_id"],
                sequence=row["sequence"],
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
            # Active tip should be the highest version in this product model.
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
        data = event.get("data") or {}
        if data.get("task") != task:
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
        data = event.get("data") or {}
        context = event.get("context") or {}
        if data.get("task") != task and context.get("llm_task") != task:
            continue
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


def audit_supervisor_chain_from_fixture(
    events: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Validate the forensic supervisor sequence against a fixture trace."""
    errors: list[str] = []
    kinds = [str(event.get("kind")) for event in events]
    required = [
        "llm.provider.request",  # analysis
        "llm.provider.response",
        "llm.output.accepted",  # SessionAnalysis
        "llm.provider.request",  # update
        "llm.provider.response",
        "llm.output.accepted",  # PostSessionUpdateResult
    ]
    # Soft structural check: both tasks appear with request/response/accepted.
    analysis_requests = [
        e
        for e in events
        if e.get("kind") == "llm.provider.request"
        and (e.get("data") or {}).get("task") == "post_session_analysis"
    ]
    update_requests = [
        e
        for e in events
        if e.get("kind") == "llm.provider.request"
        and (e.get("data") or {}).get("task") == "post_session_update"
    ]
    accepted_analysis = [
        e
        for e in events
        if e.get("kind") == "llm.output.accepted"
        and (
            (e.get("data") or {}).get("task") == "post_session_analysis"
            or (e.get("context") or {}).get("llm_task") == "post_session_analysis"
        )
    ]
    accepted_update = [
        e
        for e in events
        if e.get("kind") == "llm.output.accepted"
        and (
            (e.get("data") or {}).get("task") == "post_session_update"
            or (e.get("context") or {}).get("llm_task") == "post_session_update"
        )
    ]
    if not analysis_requests:
        errors.append("missing post_session_analysis provider request")
    if not accepted_analysis:
        errors.append("missing accepted SessionAnalysis")
    else:
        result = (accepted_analysis[0].get("data") or {}).get("result")
        if result is not None:
            try:
                SessionReview.model_validate(
                    {
                        "analysis": result,
                        "briefing": {
                            "narrative_handoff": "x",
                            "recommended_opening_focus": "y",
                        },
                        "plan_recommendation": {},
                    }
                )
            except Exception:
                # Accept either a SessionAnalysis-shaped dict or model dump.
                try:
                    from jung.domain.session_artifacts import SessionAnalysis

                    if isinstance(result, Mapping):
                        SessionAnalysis.model_validate(result)
                    else:
                        errors.append("accepted analysis is not SessionAnalysis-shaped")
                except Exception as exc:
                    errors.append(f"accepted analysis invalid: {exc}")
    if not update_requests:
        errors.append("missing post_session_update provider request")
    if not accepted_update:
        errors.append("missing accepted PostSessionUpdateResult")
    else:
        result = (accepted_update[0].get("data") or {}).get("result")
        if isinstance(result, Mapping):
            try:
                PostSessionUpdateResult.model_validate(result)
            except Exception as exc:
                errors.append(f"accepted update is not PostSessionUpdateResult: {exc}")
        else:
            errors.append("accepted update missing mapping result")
    del kinds, required
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


def render_audit_markdown(
    *,
    status: SimulationStatus,
    runtime_diagnostics_status: str | None,
    findings: Sequence[AuditFinding],
    warnings: Sequence[AuditFinding],
    run_config: Mapping[str, Any],
    artifact_index: Sequence[str],
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
        f"Runtime diagnostics: {(runtime_diagnostics_status or 'unknown').upper()}",
        "",
        "## Mechanical failures",
        "",
    ]
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
    lines.extend(["", "## Artifact index", ""])
    for item in artifact_index:
        lines.append(f"- `{item}`")
    lines.append("")
    return "\n".join(lines)


def run_mechanical_audit(
    *,
    run_dir: Path,
    provider_trace_required: bool,
    configured_sessions: int,
    therapy_sessions: Sequence[Mapping[str, Any]],
) -> AuditResult:
    """Collect forensic findings from checkpoints, final snapshot, and trace."""
    audit = AuditResult()
    checkpoints_dir = run_dir / "checkpoints"
    initial = checkpoints_dir / "initial-ready.sqlite"
    if initial.is_file():
        check_sqlite_integrity(initial, audit)
    else:
        audit.fail("missing_initial_checkpoint", "initial-ready.sqlite missing")

    snapshot = run_dir / "runtime" / "db_snapshot.sqlite"
    if not snapshot.is_file():
        audit.fail("missing_final_snapshot", "runtime/db_snapshot.sqlite missing")
        return audit

    check_sqlite_integrity(snapshot, audit)
    conn = _connect_readonly(snapshot)
    try:
        for index, session_info in enumerate(therapy_sessions, start=1):
            checkpoint = checkpoints_dir / f"after-session-{index:03d}.sqlite"
            if checkpoint.is_file():
                check_sqlite_integrity(checkpoint, audit)
            else:
                audit.fail(
                    "missing_session_checkpoint",
                    f"missing {checkpoint.name}",
                    session_number=index,
                )
            audit_completed_therapy_session(
                conn,
                session_id=str(session_info["session_id"]),
                submitted_turns=list(session_info.get("turns") or ()),
                audit=audit,
            )
        audit_grounding(conn, audit)
        audit_plan_lineage(conn, audit)
    finally:
        conn.close()

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
            )
    elif not any(event.get("kind") == "llm.provider.request" for event in trace):
        audit.warn(
            "provider_trace_unavailable",
            "llm.provider.request events absent (expected under FakeLLM)",
        )
    return audit


def _audit_provider_prompt_chains(
    *,
    audit: AuditResult,
    trace: Sequence[Mapping[str, Any]],
    configured_sessions: int,
    therapy_sessions: Sequence[Mapping[str, Any]],
    snapshot: Path,
) -> None:
    conn = _connect_readonly(snapshot)
    try:
        for index, session_info in enumerate(therapy_sessions, start=1):
            session_id = str(session_info["session_id"])
            # Supervisor chain for this session.
            analysis_reqs = find_provider_requests(
                trace,
                task="post_session_analysis",
                session_id=session_id,
            )
            update_reqs = find_provider_requests(
                trace,
                task="post_session_update",
                session_id=session_id,
            )
            if not analysis_reqs:
                audit.fail(
                    "missing_analysis_request",
                    "post_session_analysis provider request missing",
                    session_id=session_id,
                )
            if not update_reqs:
                audit.fail(
                    "missing_update_request",
                    "post_session_update provider request missing",
                    session_id=session_id,
                )
            accepted_update = find_accepted_outputs(
                trace,
                task="post_session_update",
                session_id=session_id,
            )
            if accepted_update:
                result = (accepted_update[0].get("data") or {}).get("result")
                if isinstance(result, Mapping):
                    try:
                        PostSessionUpdateResult.model_validate(result)
                    except Exception as exc:
                        audit.fail(
                            "invalid_update_result",
                            f"PostSessionUpdateResult invalid: {exc}",
                            session_id=session_id,
                        )

            for turn in session_info.get("turns") or ():
                client_message_id = str(turn["client_message_id"])
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
                    continue
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
                    continue
                current = document.get("current_patient_message")
                if current != turn["patient_text"]:
                    audit.fail(
                        "patient_message_prompt_mismatch",
                        "current_patient_message != durable/submitted patient text",
                        session_id=session_id,
                        client_message_id=client_message_id,
                    )
                historical = document.get("historical_context")
                if isinstance(historical, Mapping):
                    grounded = historical.get("grounded_patient_turns")
                    if isinstance(grounded, list):
                        _audit_grounded_prompt_contents(conn, grounded, audit=audit)

            # Briefing handoff into next session.
            if index >= configured_sessions:
                continue
            if index >= len(therapy_sessions):
                continue
            next_session = therapy_sessions[index]
            next_turns = list(next_session.get("turns") or ())
            if not next_turns:
                continue
            first = next_turns[0]
            next_requests = find_provider_requests(
                trace,
                task="therapy_response",
                session_id=str(next_session["session_id"]),
                client_message_id=str(first["client_message_id"]),
            )
            review_row = conn.execute(
                "SELECT review_json FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if review_row is None or review_row["review_json"] is None:
                audit.fail(
                    "missing_review_for_handoff",
                    "cannot verify next-session briefing without review",
                    session_id=session_id,
                )
                continue
            review = SessionReview.model_validate_json(review_row["review_json"])
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
                projected = historical.get("latest_supervisor_briefing")
                if isinstance(projected, Mapping):
                    projected = dict(projected)
                else:
                    projected = None
            for error in compare_briefing_projection(review, projected):
                audit.fail(
                    "stale_or_missing_briefing",
                    error,
                    source_session_id=session_id,
                    next_session_id=str(next_session["session_id"]),
                )
    finally:
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
        by_content.setdefault(row["content"], []).append(row["id"])
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
        candidates = by_content.get(content, [])
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
