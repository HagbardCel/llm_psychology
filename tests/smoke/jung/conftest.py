"""Pytest hooks and fixtures for Phase 3 smoke evidence output."""

from __future__ import annotations

import json

import pytest

from tests.smoke.jung.smoke_evidence import COLLECTOR


@pytest.fixture(scope="session", autouse=True)
def verify_smoke_instrumentation():
    yield
    if COLLECTOR.has_data():
        payload = json.dumps(
            COLLECTOR.to_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        print(f"PHASE3_SMOKE_EVIDENCE={payload}")
    assert not COLLECTOR.instrumentation_errors, (
        "smoke instrumentation errors: "
        f"{COLLECTOR.instrumentation_errors}"
    )
