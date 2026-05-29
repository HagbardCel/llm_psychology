"""Run-scoped SQLite export for workflow probe diagnostics."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPORT_TABLES = (
    "user_profiles",
    "sessions",
    "therapy_plans",
    "assessment_recommendations",
    "session_enrichment_jobs",
    "user_profile_history",
    "patient_analysis",
    "llm_cache",
)

TABLE_FILTERS: dict[str, tuple[str, ...]] = {
    "user_profiles": ("user_id",),
    "sessions": ("user_id", "session_id"),
    "therapy_plans": ("user_id",),
    "assessment_recommendations": ("user_id", "intake_session_block_id"),
    "session_enrichment_jobs": ("user_id", "session_id"),
    "user_profile_history": ("user_id", "created_by_session"),
    "patient_analysis": ("user_id", "created_by_session"),
    "llm_cache": ("user_id", "session_block_id"),
}

TABLE_ORDER_COLUMNS: dict[str, tuple[str, ...]] = {
    "user_profiles": ("updated_at", "created_at"),
    "sessions": ("timestamp",),
    "therapy_plans": ("created_at",),
    "assessment_recommendations": ("created_at",),
    "session_enrichment_jobs": ("updated_at", "created_at"),
    "user_profile_history": ("created_at",),
    "patient_analysis": ("version", "created_at"),
    "llm_cache": ("created_at",),
}


def export_probe_db(
    *,
    db_path: str | Path,
    export_path: str | Path,
    latest_export_path: str | Path,
    scenario_id: str,
    user_id: str,
    session_ids: list[str],
) -> dict[str, Any]:
    """Export rows associated with a workflow probe run."""
    resolved_db_path = Path(db_path)
    output_path = Path(export_path)
    latest_path = Path(latest_export_path)
    unique_session_ids = _dedupe(session_ids)

    tables = {table: [] for table in EXPORT_TABLES}
    plan_ids: list[str] = []

    if resolved_db_path.exists():
        conn = sqlite3.connect(resolved_db_path)
        conn.row_factory = sqlite3.Row
        try:
            for table in EXPORT_TABLES:
                rows = _fetch_table_rows(
                    conn,
                    table_name=table,
                    user_id=user_id,
                    session_ids=unique_session_ids,
                )
                tables[table] = rows
                _collect_plan_ids(plan_ids, rows)
        finally:
            conn.close()

    payload = {
        "metadata": {
            "scenario_id": scenario_id,
            "user_id": user_id,
            "session_ids": unique_session_ids,
            "plan_ids": plan_ids,
            "db_path": str(resolved_db_path),
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
        "tables": tables,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    shutil.copyfile(output_path, latest_path)
    return payload


def _fetch_table_rows(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    user_id: str,
    session_ids: list[str],
) -> list[dict[str, Any]]:
    columns = _table_columns(conn, table_name)
    if not columns:
        return []

    clauses: list[str] = []
    params: list[str] = []
    for column in TABLE_FILTERS[table_name]:
        if column == "user_id" and column in columns:
            clauses.append(f"{column} = ?")
            params.append(user_id)
        elif column in columns and session_ids:
            placeholders = ", ".join("?" for _ in session_ids)
            clauses.append(f"{column} IN ({placeholders})")
            params.extend(session_ids)

    if not clauses:
        return []

    sql = f"SELECT * FROM {table_name} WHERE {' OR '.join(clauses)}"
    order_by = _order_by_clause(columns, TABLE_ORDER_COLUMNS.get(table_name, ()))
    if order_by:
        sql = f"{sql} ORDER BY {order_by}"

    cursor = conn.execute(sql, params)
    return [dict(row) for row in cursor.fetchall()]


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    if not cursor.fetchone():
        return set()
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]) for row in cursor.fetchall()}


def _order_by_clause(columns: set[str], candidates: tuple[str, ...]) -> str:
    order_columns = [column for column in candidates if column in columns]
    return ", ".join(f"{column} ASC" for column in order_columns)


def _collect_plan_ids(plan_ids: list[str], rows: list[dict[str, Any]]) -> None:
    seen = set(plan_ids)
    for row in rows:
        plan_id = row.get("plan_id")
        if plan_id is None:
            continue
        plan_id_text = str(plan_id)
        if plan_id_text and plan_id_text not in seen:
            seen.add(plan_id_text)
            plan_ids.append(plan_id_text)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            deduped.append(text)
    return deduped
