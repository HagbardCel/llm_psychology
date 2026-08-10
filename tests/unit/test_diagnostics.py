"""Unit tests for lean diagnostic logging."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

import jung.diagnostics as diagnostics
from jung.composition import application_context
from jung.diagnostics import (
    DiagnosticRecorder,
    diagnostic_context,
    sanitize_url,
    sanitize_value,
    snapshot_database,
)
from jung.domain.models import Profile
from jung.persistence.sqlite_store import SQLiteStore
from tests.support.settings import make_test_settings


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


def test_sanitize_value_redacts_short_caller_designated_secrets() -> None:
    secret = "abc123"
    sanitized = sanitize_value(
        {"error_message": f"authentication failed for {secret}"},
        secret_values=[secret],
    )
    assert sanitized["error_message"] == "authentication failed for [REDACTED]"


def test_recorder_redacts_short_configured_secrets(tmp_path: Path) -> None:
    secret = "abc123"
    with DiagnosticRecorder(tmp_path / "run", secret_values=[secret]) as recorder:
        recorder.record(
            "operation.failed",
            {"error_message": f"authentication failed for {secret}"},
        )
    lines = _trace_lines(tmp_path / "run")
    status = next(e for e in lines if e["kind"] == "operation.failed")
    assert status["data"]["error_message"] == "authentication failed for [REDACTED]"


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
        with diagnostic_context(unexpected_field="x"):
            pass


def test_diagnostic_context_field_inventory() -> None:
    import jung.diagnostics as diagnostics

    assert frozenset(diagnostics.DiagnosticContext.__dataclass_fields__) == {
        "request_id",
        "session_id",
        "client_message_id",
        "operation_id",
        "llm_call_id",
    }


def test_diagnostic_context_nested_merge_and_restore() -> None:
    with diagnostic_context(session_id="s1"):
        with diagnostic_context(operation_id="o1", client_message_id="c1"):
            with diagnostic_context(llm_call_id="llm-1"):
                from jung.diagnostics import current_diagnostic_context

                ctx = current_diagnostic_context()
                assert ctx.session_id == "s1"
                assert ctx.operation_id == "o1"
                assert ctx.client_message_id == "c1"
                assert ctx.llm_call_id == "llm-1"
            from jung.diagnostics import current_diagnostic_context

            mid = current_diagnostic_context()
            assert mid.llm_call_id is None
            assert mid.client_message_id == "c1"
        outer = __import__(
            "jung.diagnostics", fromlist=["current_diagnostic_context"]
        ).current_diagnostic_context()
        assert outer.operation_id is None
        assert outer.session_id == "s1"


def test_recorder_envelope_sequence_and_context(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    with DiagnosticRecorder(run_dir) as recorder:
        with diagnostic_context(session_id="s1", operation_id="o1"):
            recorder.record("llm.provider.request", {"attempt": "initial"})
    lines = _trace_lines(run_dir)
    assert lines[0]["kind"] == "diagnostics.start"
    assert lines[-1]["kind"] == "diagnostics.end"
    assert lines[-1]["data"]["status"] == "success"
    event = lines[1]
    assert event["schema_version"] == 5
    assert event["sequence"] == 2
    assert "timestamp" in event
    assert "elapsed_ms" in event
    assert event["kind"] == "llm.provider.request"
    assert event["context"]["session_id"] == "s1"
    assert event["context"]["operation_id"] == "o1"
    assert "run_id" in event["context"]
    assert event["data"]["attempt"] == "initial"


def test_top_level_exception_records_error_and_propagates(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    with pytest.raises(RuntimeError, match="boom"):
        with DiagnosticRecorder(run_dir) as recorder:
            recorder.record("test.event", {"value": 1})
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
        DiagnosticRecorder(run_dir)


def test_write_failure_latches_and_warns_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "run"
    with DiagnosticRecorder(run_dir) as recorder:
        real_write = recorder._trace_file.write

        def flaky_write(text: str) -> int:
            if '"kind":"test.event"' in text.replace(" ", ""):
                raise OSError("disk full")
            return real_write(text)

        monkeypatch.setattr(recorder._trace_file, "write", flaky_write)
        recorder.record("test.event", {"value": 1})
        recorder.record("test.event", {"value": 2})
        recorder.record("test.event", {"value": 3})
    err = capsys.readouterr().err
    assert err.count("jung diagnostics:") == 1


def test_thread_safe_sequence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    with DiagnosticRecorder(run_dir) as recorder:

        def worker(n: int) -> None:
            for i in range(20):
                recorder.record("test.event", {"n": n, "i": i})

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    lines = _trace_lines(run_dir)
    sequences = [line["sequence"] for line in lines]
    assert sequences == list(range(1, len(sequences) + 1))


def test_concurrent_record_cannot_append_after_diagnostics_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary record admitted before shutdown must not outrank diagnostics.end.

    Forces a record into the dangerous interval: past preparation / unlocked
    admission, delayed around the persistence lock, while close claims shutdown,
    writes the terminal event, and only then releases the held file-close gate.
    """
    run_dir = tmp_path / "run"
    recorder = DiagnosticRecorder(run_dir)

    record_entered = threading.Event()
    allow_record_persist = threading.Event()
    file_close_entered = threading.Event()
    allow_file_close = threading.Event()

    original_write_line = DiagnosticRecorder._write_line

    def gated_write_line(
        self: DiagnosticRecorder,
        kind: str,
        data: dict,
        *,
        raise_on_error: bool,
    ) -> None:
        if kind not in ("diagnostics.start", "diagnostics.end"):
            record_entered.set()
            assert allow_record_persist.wait(timeout=5.0)
        return original_write_line(self, kind, data, raise_on_error=raise_on_error)

    monkeypatch.setattr(DiagnosticRecorder, "_write_line", gated_write_line)

    real_close = recorder._trace_file.close

    def gated_file_close() -> None:
        file_close_entered.set()
        assert allow_file_close.wait(timeout=5.0)
        return real_close()

    monkeypatch.setattr(recorder._trace_file, "close", gated_file_close)

    errors: list[BaseException] = []

    def record_worker() -> None:
        try:
            recorder.record("test.event", {"marker": "after-admit"})
        except BaseException as exc:  # noqa: BLE001 - collect for main thread
            errors.append(exc)

    thread = threading.Thread(target=record_worker)
    thread.start()
    assert record_entered.wait(timeout=5.0)

    close_done = threading.Event()

    def close_worker() -> None:
        try:
            recorder.close()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            close_done.set()

    close_thread = threading.Thread(target=close_worker)
    close_thread.start()
    assert file_close_entered.wait(timeout=5.0)

    allow_record_persist.set()
    allow_file_close.set()
    assert close_done.wait(timeout=5.0)
    thread.join(timeout=5.0)
    close_thread.join(timeout=5.0)
    assert errors == []

    kinds = [line["kind"] for line in _trace_lines(run_dir)]
    assert kinds.count("diagnostics.end") == 1
    assert kinds[-1] == "diagnostics.end"


def test_secure_permissions(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    with DiagnosticRecorder(run_dir):
        pass
    assert oct(run_dir.stat().st_mode & 0o777) == "0o700"
    assert oct((run_dir / "trace.jsonl").stat().st_mode & 0o777) == "0o600"


def test_existing_dir_fails_startup(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(FileExistsError):
        with DiagnosticRecorder(run_dir):
            pass


@pytest.mark.asyncio
async def test_disabled_mode_creates_no_artifacts(tmp_path: Path) -> None:
    class _StubLLM:
        async def aclose(self) -> None:
            return None

    settings = make_test_settings(
        data_dir=tmp_path,
        llm_base_url="http://127.0.0.1:9/v1",
        llm_api_key="test-key",
        model_name="test-model",
        debug_run_dir=None,
    )
    async with application_context(
        settings,
        llm_factory=lambda _config, _recorder: _StubLLM(),  # type: ignore[return-value]
    ) as application:
        await application.get_snapshot()
    assert list(tmp_path.glob("**/trace.jsonl")) == []


def test_snapshot_database_handles_reserved_path_chars(tmp_path: Path) -> None:
    db_dir = tmp_path / "db with spaces?#frag"
    db_dir.mkdir()
    db_path = db_dir / "jung.db"
    store = SQLiteStore(db_path)
    store.initialize()
    store.update_profile(
        Profile(name="Alex", primary_language="English"),
        intake_session_id=uuid4(),
        now=datetime.now(UTC),
    )
    destination = tmp_path / "db_snapshot.sqlite"
    snapshot_database(db_path, destination)
    assert destination.exists()
    conn = sqlite3.connect(destination)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert len(tables) > 0


def test_snapshot_database_refuses_overwrite(tmp_path: Path) -> None:
    db_path = tmp_path / "jung.db"
    SQLiteStore(db_path).initialize()
    destination = tmp_path / "db_snapshot.sqlite"
    snapshot_database(db_path, destination)
    with pytest.raises(FileExistsError):
        snapshot_database(db_path, destination)


def test_snapshot_database_cleans_up_after_post_create_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "jung.db"
    SQLiteStore(db_path).initialize()
    destination = tmp_path / "db_snapshot.sqlite"

    def boom(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(diagnostics.sqlite3, "connect", boom)
    with pytest.raises(KeyboardInterrupt):
        snapshot_database(db_path, destination)
    assert not destination.exists()


def test_snapshot_database_cleans_up_when_close_fails_after_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "jung.db"
    SQLiteStore(db_path).initialize()
    destination = tmp_path / "db_snapshot.sqlite"

    real_close = diagnostics.os.close

    def close_then_fail(fd: int) -> None:
        real_close(fd)
        raise OSError("forced close failure")

    monkeypatch.setattr(diagnostics.os, "close", close_then_fail)
    with pytest.raises(OSError, match="forced close failure"):
        snapshot_database(db_path, destination)
    assert not destination.exists()
