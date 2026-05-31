"""Consistent SQLite snapshots and attributable row extraction."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


TABLES = (
    "user_profiles", "sessions", "therapy_plans", "assessment_recommendations",
    "session_enrichment_jobs", "user_profile_history", "patient_analysis", "llm_cache",
)


def session_enrichment_complete(
    db_path: str | Path, user_id: str, session_ids: list[str]
) -> bool:
    """Return whether attributable session enrichment jobs and sessions completed."""
    if not session_ids or not Path(db_path).exists():
        return False
    marks = ", ".join("?" for _ in session_ids)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        sessions = conn.execute(
            f"SELECT session_id, session_type, enriched FROM sessions "
            f"WHERE user_id = ? AND session_id IN ({marks})",
            [user_id, *session_ids],
        ).fetchall()
        therapy_ids = [
            row["session_id"]
            for row in sessions
            if row["session_type"] == "therapy"
        ]
        if not therapy_ids or any(
            not row["enriched"] for row in sessions if row["session_type"] == "therapy"
        ):
            return False
        job_marks = ", ".join("?" for _ in therapy_ids)
        jobs = conn.execute(
            f"SELECT status FROM session_enrichment_jobs "
            f"WHERE user_id = ? AND session_id IN ({job_marks})",
            [user_id, *therapy_ids],
        ).fetchall()
    return bool(jobs) and all(row["status"] == "complete" for row in jobs)


def snapshot_and_extract(db_path: str | Path, output_dir: str | Path, user_id: str, session_ids: list[str]) -> dict[str, Any]:
    source_path = Path(db_path)
    output_path = Path(output_dir)
    snapshot_path = output_path / "db_snapshot.sqlite"
    if not source_path.exists():
        with sqlite3.connect(snapshot_path) as snapshot:
            integrity = snapshot.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                raise RuntimeError(f"SQLite snapshot integrity check failed: {integrity}")
        payload = {table: [] for table in TABLES}
        (output_path / "created_rows.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return payload
    with sqlite3.connect(source_path) as source, sqlite3.connect(snapshot_path) as snapshot:
        source.backup(snapshot)
    with sqlite3.connect(snapshot_path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise RuntimeError(f"SQLite snapshot integrity check failed: {integrity}")
        conn.row_factory = sqlite3.Row
        payload = {table: _rows_for_table(conn, table, user_id, session_ids) for table in TABLES}
    (output_path / "created_rows.json").write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return payload


def _rows_for_table(conn: sqlite3.Connection, table: str, user_id: str, session_ids: list[str]) -> list[dict[str, Any]]:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if not columns:
        return []
    if "user_id" in columns:
        return _fetch(conn, table, "user_id = ?", [user_id])
    for column in ("session_id", "created_by_session", "intake_session_block_id", "session_block_id"):
        if column in columns and session_ids:
            marks = ", ".join("?" for _ in session_ids)
            return _fetch(conn, table, f"{column} IN ({marks})", session_ids)
    return []


def _fetch(conn: sqlite3.Connection, table: str, where: str, params: list[str]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE {where}", params)]
