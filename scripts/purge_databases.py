"""Purge local and usertest SQLite databases."""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_LOCAL_DB = Path("data/psychoanalyst.db")
DEFAULT_USERTEST_DB = Path("data/psychoanalyst_usertest.db")


def _delete_sqlite_artifacts(db_path: Path) -> list[Path]:
    removed = []
    for suffix in ("", "-shm", "-wal"):
        candidate = Path(f"{db_path}{suffix}")
        if candidate.exists():
            candidate.unlink()
            removed.append(candidate)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Purge local and usertest SQLite database files."
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Purge the local database (data/psychoanalyst.db)",
    )
    parser.add_argument(
        "--usertest",
        action="store_true",
        help="Purge the usertest database (data/psychoanalyst_usertest.db)",
    )
    args = parser.parse_args()

    targets = []
    if not args.local and not args.usertest:
        targets = [DEFAULT_LOCAL_DB, DEFAULT_USERTEST_DB]
    else:
        if args.local:
            targets.append(DEFAULT_LOCAL_DB)
        if args.usertest:
            targets.append(DEFAULT_USERTEST_DB)

    removed_total = []
    for db_path in targets:
        removed_total.extend(_delete_sqlite_artifacts(db_path))

    if removed_total:
        print("Removed:")
        for item in removed_total:
            print(f"- {item}")
    else:
        print("No database files found to purge.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
