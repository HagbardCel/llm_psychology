"""Pytest hooks and fixtures for local-model smoke evidence output."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jung.diagnostics import DiagnosticRun, sanitize_url
from tests.smoke.jung.smoke_evidence import COLLECTOR, render_smoke_evidence

_session_failed = False


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]) -> None:
    global _session_failed
    if call.excinfo is not None:
        _session_failed = True


@pytest.fixture(scope="session")
def diagnostic_run(request: pytest.FixtureRequest):
    raw = os.environ.get("JUNG_DEBUG_RUN_DIR", "").strip()
    if not raw:
        yield None
        return

    metadata = {
        "server": os.environ.get("LOCAL_LLM_SMOKE_SERVER"),
        "model": os.environ.get("LOCAL_LLM_SMOKE_MODEL"),
        "provider_base_url": sanitize_url(
            os.environ.get("LOCAL_LLM_SMOKE_BASE_URL", "")
        ),
        "structured_mode": os.environ.get(
            "LOCAL_LLM_SMOKE_STRUCTURED_MODE",
            "json_schema",
        ),
    }
    secret_values = [os.environ.get("OPENAI_API_KEY", "")]
    with DiagnosticRun(
        Path(raw),
        metadata=metadata,
        secret_values=secret_values,
    ) as recorder:
        yield recorder
        if _session_failed or request.session.testsfailed:
            recorder.mark_run_failed()


@pytest.fixture(scope="session", autouse=True)
def print_smoke_evidence():
    yield
    evidence_line = render_smoke_evidence(COLLECTOR)
    if evidence_line is not None:
        print(evidence_line)
