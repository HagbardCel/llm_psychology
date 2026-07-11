#!/usr/bin/env python3
"""Print the Phase 1 completion commit SHA from baseline-metrics.md."""

from __future__ import annotations

import re
from pathlib import Path


def extract_baseline_sha(root: Path | None = None) -> str:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    text = (root / "docs/refactor/baseline-metrics.md").read_text(encoding="utf-8")
    match = re.search(r"`([0-9a-f]{40})`", text)
    if not match:
        raise SystemExit("baseline-metrics.md missing 40-char SHA")
    return match.group(1)


def main() -> int:
    print(extract_baseline_sha())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
