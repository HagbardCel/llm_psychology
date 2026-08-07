"""Unit tests for lean diagnostic logging."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import BaseModel

from jung.composition import application_context
from jung.config import ApplicationSettings
from jung.diagnostics import (
    DiagnosticRecorder,
    DiagnosticRun,
    diagnostic_context,
    sanitize_url,
    sanitize_value,
)
from jung.llm.gateway import LLMSettings


class _Kind(Enum):
    ALPHA = "alpha"


class _Model(BaseModel):
    name: str
    api_key: str


def _trace_lines(run_dir: Path) -> list[dict]:
    path = run_dir / "trace.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_sanitize_url_strips_userinfo_and_query() -> None:
    assert (
        sanitize_url("https://user:secret@example.test:8443/v1/chat?token=1#frag")
        == "https://example.test:8443/v1/chat"
    )


def test_sanitize_url_invalid_returns_placeholder() -> None:
    assert sanitize_url("http://[bad") == "[REDACTED_URL]"


@pytest.mark.parametrize(
    ("key", "expected_redacted"),
    [
        ("prompt_tokens", False),
        ("completion_tokens", False),
        ("max_completion_tokens", False),
        ("total_tokens", False),
        ("token", True),
        ("access_token", True),
        ("api-key", True),
        ("Authorization", True),
        ("client_secret", True),
    ],
)
def test_sanitize_value_token_metric_allowlist(
    key: str,
    expected_redacted: bool,
) -> None:
    sanitized = sanitize_value({key: 42 if not expected_redacted else "secret"})
    if expected_redacted:
        assert sanitized[key] == "[REDACTED]"
    else:
        assert sanitized[key] == 42


def test_sanitize_value_exact_secret_replacement() -> None:
    secret = "sk-super-secret-value"
    sanitized = sanitize_value(
        {"message": f"failed using {secret}"},
        secret_values=[secret],
    )
    assert sanitized["message"] == "failed using [REDACTED]"


def test_sanitize_value_common_project_types() -> None:
    payload = {
        "uuid": UUID("00000000-0000-0000-0000-000000000001"),
        "when": datetime(2026, 1, 2, 3, 4, 5),
        "day": date(2026, 1, 2),
        "kind": _Kind.ALPHA,
        "model": _Model(name="x", api_key="secret-key"),
        "path": Path("/tmp/x"),
    }
    sanitized = sanitize_value(payload)
    assert sanitized["uuid"] == "00000000-0000-0000-0000-000000000001"
    assert sanitized["kind"] == "alpha"
    assert sanitized["model"]["api_key"] == "[REDACTED]"


def test_diagnostic_context_rejects_unknown_fields() -> None:
    with pytest.raises(TypeError, match="unknown diagnostic context fields"):
        with diagnostic_context(task_name="old"):
            pass


def test_diagnostic_context_nested_merge_and_restore() -> None:
    with diagnostic_context(session_id="s1"):
        with diagnostic_context(operation_id="o1", task="t1"):
            with diagnostic_context(llm_call_id="llm-1"):
                from jung.diagnostics import current_diagnostic_context

                ctx = current_diagnostic_context()
                assert ctx.session_id == "s1"
                assert ctx.operation_id == "o1"
                assert ctx.task == "t1"
                assert ctx.llm_call_id == "llm-1"
            from jung.diagnostics import current_diagnostic_context

            mid = current_diagnostic_context()
            assert mid.llm_call_id is None
            assert mid.task == "t1"
        outer = __import__(
            "jung.diagnostics", fromlist=["current_diagnostic_context"]
        ).current_diagnostic_context()
        assert outer.operation_id is None
        assert outer.session_id == "s1"


def test_recorder_envelope_sequence_and_context(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    with DiagnosticRun(run_dir) as recorder:
        with diagnostic_context(session_id="s1", task="chat:1"):
            recorder.record("llm.provider.request", {"attempt": "initial"})
    lines = _trace_lines(run_dir)
    assert lines[0]["kind"] == "diagnostics.start"
    assert lines[-1]["kind"] == "diagnostics.end"
    assert lines[-1]["data"]["status"] == "success"
    event = lines[1]
    assert event["schema_version"] == 1
    assert event["sequence"] == 2
    assert "timestamp" in event
    assert "elapsed_ms" in event
    assert event["kind"] == "llm.provider.request"
    assert event["context"] == {"session_id": "s1", "task": "chat:1"}
    assert event["data"]["attempt"] == "initial"
    assert not (run_dir / "manifest.json").exists()


def test_mark_run_failed_sets_end_status_without_raising(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    with DiagnosticRun(run_dir) as recorder:
        recorder.mark_run_failed()
    end = _trace_lines(run_dir)[-1]
    assert end["kind"] == "diagnostics.end"
    assert end["data"] == {"status": "failed"}


def test_top_level_exception_records_error_and_propagates(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    with pytest.raises(RuntimeError, match="boom"):
        with DiagnosticRun(run_dir) as recorder:
            recorder.record("workflow.state", {"revision": 1, "stage": "intake"})
            raise RuntimeError("boom")
    end = _trace_lines(run_dir)[-1]
    assert end["data"]["status"] == "failed"
    assert end["data"]["error_type"] == "RuntimeError"
    assert end["data"]["error_message"] == "boom"


def test_diagnostics_start_write_failure_fails_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"

    def boom_write(self, kind, data, *, raise_on_error):  # type: ignore[no-untyped-def]
        if kind == "diagnostics.start":
            raise OSError("disk full")
        raise AssertionError("unexpected write")

    monkeypatch.setattr(DiagnosticRecorder, "_write_line", boom_write)
    with pytest.raises(OSError, match="disk full"):
        DiagnosticRun(run_dir).__enter__()


def test_write_failure_latches_and_warns_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "run"
    with DiagnosticRun(run_dir) as recorder:
        real_write = recorder._trace_file.write

        def flaky_write(text: str) -> int:
            if '"kind":"workflow.state"' in text.replace(" ", ""):
                raise OSError("disk full")
            return real_write(text)

        monkeypatch.setattr(recorder._trace_file, "write", flaky_write)
        recorder.record("workflow.state", {"revision": 1, "stage": "intake"})
        recorder.record("workflow.state", {"revision": 2, "stage": "therapy"})
        recorder.record("workflow.state", {"revision": 3, "stage": "ready"})
    err = capsys.readouterr().err
    assert err.count("jung diagnostics:") == 1


def test_thread_safe_sequence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    with DiagnosticRun(run_dir) as recorder:

        def worker(n: int) -> None:
            for i in range(20):
                recorder.record("workflow.state", {"n": n, "i": i})

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    lines = _trace_lines(run_dir)
    sequences = [line["sequence"] for line in lines]
    assert sequences == list(range(1, len(sequences) + 1))


def test_secure_permissions(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    with DiagnosticRun(run_dir):
        pass
    assert oct(run_dir.stat().st_mode & 0o777) == "0o700"
    assert oct((run_dir / "trace.jsonl").stat().st_mode & 0o777) == "0o600"


def test_existing_dir_fails_startup(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(FileExistsError):
        with DiagnosticRun(run_dir):
            pass


@pytest.mark.asyncio
async def test_disabled_mode_creates_no_artifacts(tmp_path: Path) -> None:
    class _StubLLM:
        async def aclose(self) -> None:
            return None

    settings = ApplicationSettings(
        database_path=tmp_path / "jung.db",
        llm=LLMSettings(
            base_url="http://127.0.0.1:9/v1",
            api_key="test-key",
            default_model="test-model",
        ),
        debug_run_dir=None,
    )
    async with application_context(
        settings,
        llm_factory=lambda _config, _recorder: _StubLLM(),  # type: ignore[return-value]
    ) as runtime:
        assert not hasattr(runtime, "recorder")
        await runtime.application.get_snapshot()
    assert list(tmp_path.glob("**/trace.jsonl")) == []
