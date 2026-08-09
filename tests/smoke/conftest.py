"""Pytest hooks and fixtures for local-model smoke evidence output."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jung.diagnostics import DiagnosticRecorder
from tests.smoke.smoke_evidence import COLLECTOR, render_smoke_evidence

_session_failed = False


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    global _session_failed
    if report.failed:
        _session_failed = True


@pytest.fixture(scope="session")
def diagnostic_run(request: pytest.FixtureRequest):
    raw = os.environ.get("JUNG_DEBUG_RUN_DIR", "").strip()
    if not raw:
        yield None
        return

    secret_values = [os.environ.get("OPENAI_API_KEY", "")]
    with DiagnosticRecorder(
        Path(raw),
        secret_values=secret_values,
    ) as recorder:
        yield recorder
        if _session_failed or request.session.testsfailed:
            recorder.close(
                primary_exception=RuntimeError("local-model smoke failed")
            )


@pytest.fixture(scope="session", autouse=True)
def print_smoke_evidence():
    yield
    evidence_line = render_smoke_evidence(COLLECTOR)
    if evidence_line is not None:
        print(evidence_line)
