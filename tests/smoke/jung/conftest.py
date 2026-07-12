"""Pytest hooks for Phase 3 smoke evidence output."""

from __future__ import annotations

import json

import pytest

from tests.smoke.jung.smoke_evidence import COLLECTOR


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not COLLECTOR.has_data():
        return
    payload = json.dumps(
        COLLECTOR.to_payload(),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    print(f"PHASE3_SMOKE_EVIDENCE={payload}")
