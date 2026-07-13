"""Pytest hooks and fixtures for Phase 3 smoke evidence output."""

from __future__ import annotations

import pytest

from tests.smoke.jung.smoke_evidence import COLLECTOR, render_smoke_evidence


@pytest.fixture(scope="session", autouse=True)
def verify_smoke_instrumentation():
    yield
    evidence_line = render_smoke_evidence(COLLECTOR)
    if evidence_line is not None:
        print(evidence_line)
    assert not COLLECTOR.instrumentation_errors, (
        "smoke instrumentation errors: "
        f"{COLLECTOR.instrumentation_errors}"
    )
