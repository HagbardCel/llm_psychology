"""Scenario loading for the local workflow probe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_scenario(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as fh:
        scenario = json.load(fh)
    if not scenario.get("id"):
        raise ValueError("Probe scenario requires an id")
    return scenario
