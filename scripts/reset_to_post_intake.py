"""Reset a user back to the post-intake workflow state."""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset user data to the post-intake workflow state."
    )
    parser.add_argument("--user-id", required=True, help="User identifier")
    parser.add_argument(
        "--db-path",
        default=os.getenv("DATABASE_PATH", "data/psychoanalyst.db"),
        help="Path to the SQLite database file",
    )
    return parser.parse_args()


def _execute(cur: sqlite3.Cursor, query: str, params: tuple[str, ...]) -> int:
    cur.execute(query, params)
    return cur.rowcount


def main() -> int:
    args = _parse_args()
    conn = sqlite3.connect(args.db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM user_profiles WHERE user_id = ?",
        (args.user_id,),
    )
    if not cur.fetchone():
        print(f"User not found: {args.user_id}")
        return 1

    now = datetime.utcnow().isoformat()
    updated_profiles = _execute(
        cur,
        "UPDATE user_profiles SET status = ?, plan_id = NULL, updated_at = ? WHERE user_id = ?",
        ("INTAKE_COMPLETE", now, args.user_id),
    )
    updated_sessions = _execute(
        cur,
        "UPDATE sessions SET plan_id = NULL WHERE user_id = ?",
        (args.user_id,),
    )
    deleted_plans = _execute(
        cur, "DELETE FROM therapy_plans WHERE user_id = ?", (args.user_id,)
    )
    deleted_analysis = _execute(
        cur, "DELETE FROM patient_analysis WHERE user_id = ?", (args.user_id,)
    )
    deleted_recs = _execute(
        cur,
        "DELETE FROM assessment_recommendations WHERE user_id = ?",
        (args.user_id,),
    )
    deleted_jobs = _execute(
        cur,
        "DELETE FROM session_enrichment_jobs WHERE user_id = ?",
        (args.user_id,),
    )

    conn.commit()
    conn.close()

    print(f"Reset user {args.user_id} to INTAKE_COMPLETE")
    print(f"- user_profiles updated: {updated_profiles}")
    print(f"- sessions plan_id cleared: {updated_sessions}")
    print(f"- therapy_plans deleted: {deleted_plans}")
    print(f"- patient_analysis deleted: {deleted_analysis}")
    print(f"- assessment_recommendations deleted: {deleted_recs}")
    print(f"- session_enrichment_jobs deleted: {deleted_jobs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
