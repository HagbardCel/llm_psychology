"""Unit tests for diagnostic capture."""

from __future__ import annotations

import json
import logging
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
    DiagnosticCaptureError,
    DiagnosticRecorder,
    DiagnosticRun,
    diagnostic_context,
    sanitize_url,
    sanitize_value,
)
from jung.llm.fake import FakeLLM
from jung.llm.gateway import LLMSettings


class _Kind(Enum):
    ALPHA = "alpha"


class _Model(BaseModel):
    name: str
    api_key: str


def test_sanitize_url_strips_userinfo_and_query() -> None:
    assert (
        sanitize_url("https://user:secret@example.test:8443/v1/chat?token=1#frag")
        == "https://example.test:8443/v1/chat"
    )


def test_sanitize_url_invalid_returns_placeholder() -> None:
    assert sanitize_url("http://[bad") == "[REDACTED_URL]"


def test_sanitize_url_non_numeric_port_returns_placeholder() -> None:
    assert sanitize_url("http://localhost:not-a-port/v1") == "[REDACTED_URL]"


def test_sanitize_url_localhost() -> None:
    assert sanitize_url("http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080/v1"


@pytest.mark.parametrize(
    ("key", "expected_redacted"),
    [
        ("prompt_tokens", False),
        ("completion_tokens", False),
        ("max_completion_tokens", False),
        ("total_tokens", False),
        ("token", True),
        ("access_token", True),
        ("access_tokens", True),
        ("refresh_tokens", True),
        ("client_secret", True),
        ("api-key", True),
        ("Authorization", True),
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


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("promptTokens", 12, 12),
        ("maxCompletionTokens", None, None),
        ("promptTokens", True, "[REDACTED]"),
        ("promptTokens", "secret", "[REDACTED]"),
    ],
)
def test_sanitize_value_token_metric_numeric_only(
    key: str,
    value: object,
    expected: object,
) -> None:
    sanitized = sanitize_value({key: value})
    assert sanitized[key] == expected


@pytest.mark.parametrize(
    "key",
    [
        "accessToken",
        "secondaryAccessToken",
        "providerRefreshToken",
        "serviceClientSecret",
        "bearerTokens",
    ],
)
def test_sanitize_value_camelcase_credentials_redacted(key: str) -> None:
    sanitized = sanitize_value({key: "credential"})
    assert sanitized[key] == "[REDACTED]"


def test_sanitize_value_redacts_sensitive_keys_and_secret_values() -> None:
    secret = "super-secret-value"
    payload = {
        "Authorization": "Bearer leaked",
        "nested": {"api_key": "nested-secret", "ok": f"prefix-{secret}-suffix"},
        "list": [secret, {"token": "x"}],
        "bytes": b"abc",
        "path": Path("/tmp/x"),
        "uuid": UUID("00000000-0000-0000-0000-000000000001"),
        "when": datetime(2024, 1, 2, 3, 4, 5),
        "day": date(2024, 1, 2),
        "kind": _Kind.ALPHA,
        "model": _Model(name="n", api_key="model-secret"),
    }
    sanitized = sanitize_value(payload, secret_values=[secret])
    assert sanitized["Authorization"] == "[REDACTED]"
    assert sanitized["nested"]["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["ok"] == "prefix-[REDACTED]-suffix"
    assert sanitized["list"][0] == "[REDACTED]"
    assert sanitized["list"][1]["token"] == "[REDACTED]"
    assert sanitized["bytes"] == "<bytes:3>"
    assert sanitized["path"] == "/tmp/x"
    assert sanitized["uuid"] == "00000000-0000-0000-0000-000000000001"
    assert sanitized["when"].startswith("2024-01-02T03:04:05")
    assert sanitized["day"] == "2024-01-02"
    assert sanitized["kind"] == "alpha"
    assert sanitized["model"]["api_key"] == "[REDACTED]"
    assert sanitized["model"]["name"] == "n"


def test_sanitize_value_caps_depth() -> None:
    nested: dict[str, object] = {"v": 1}
    current = nested
    for _ in range(40):
        nxt: dict[str, object] = {"v": 1}
        current["child"] = nxt
        current = nxt
    sanitized = sanitize_value(nested)
    depth = 0
    cursor: object = sanitized
    while isinstance(cursor, dict) and "child" in cursor:
        cursor = cursor["child"]
        depth += 1
    assert depth <= 33
    assert cursor == "<max-depth>" or (
        isinstance(cursor, dict) and cursor.get("child") == "<max-depth>"
    )


def test_recorder_rejects_existing_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "existing"
    run_dir.mkdir()
    with pytest.raises(FileExistsError):
        DiagnosticRecorder(run_dir)


def test_artifact_path_rejects_invalid_names(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    recorder = DiagnosticRecorder(run_dir)
    try:
        for name in (
            "",
            "manifest.json",
            "trace.jsonl",
            "a/b",
            "a\\b",
            ".",
            "..",
            "foo/../bar",
        ):
            with pytest.raises(ValueError, match="invalid diagnostic artifact name"):
                recorder.artifact_path(name)
        assert recorder.artifact_path("database-start.sqlite") == (
            run_dir / "database-start.sqlite"
        )
    finally:
        recorder.close(run_status="success")


def test_monotonic_sequence_and_secret_redaction_in_trace(tmp_path: Path) -> None:
    secret = "abcd1234secret"
    run_dir = tmp_path / "seq"
    recorder = DiagnosticRecorder(run_dir, secret_values=[secret])
    try:
        with diagnostic_context(request_id="req-1"):
            recorder.record("event.a", {"note": f"has {secret}"})
            recorder.record("event.b", {"Authorization": "Bearer x"})
        lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 2
        first = json.loads(lines[0])
        second = json.loads(lines[1])
        assert first["sequence"] == 1
        assert second["sequence"] == 2
        assert first["context"]["request_id"] == "req-1"
        assert secret not in lines[0]
        assert "[REDACTED]" in first["data"]["note"]
        assert second["data"]["Authorization"] == "[REDACTED]"
    finally:
        recorder.close(run_status="success")


def test_concurrent_writes_are_serialized(tmp_path: Path) -> None:
    run_dir = tmp_path / "concurrent"
    recorder = DiagnosticRecorder(run_dir)
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            for step in range(20):
                recorder.record("concurrent", {"worker": index, "step": step})
        except BaseException as exc:  # noqa: BLE001 - collect for assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            assert not thread.is_alive()
        assert errors == []
        lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        sequences = [json.loads(line)["sequence"] for line in lines]
        assert sequences == list(range(1, len(sequences) + 1))
        assert len(sequences) == 160
    finally:
        recorder.close(run_status="success")


def test_log_handler_does_not_recurse(tmp_path: Path) -> None:
    run_dir = tmp_path / "logs"
    recorder = DiagnosticRecorder(run_dir)
    try:
        logger = logging.getLogger("jung.test.diagnostics")
        logger.setLevel(logging.INFO)
        logger.info("hello from app logger", extra={"api_key": "should-redact"})
        lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        assert any('"kind":"log.record"' in line for line in lines)
        payload = next(
            json.loads(line)
            for line in lines
            if json.loads(line)["kind"] == "log.record"
        )
        assert payload["data"]["message"] == "hello from app logger"
        assert payload["data"]["extra"]["api_key"] == "[REDACTED]"
    finally:
        recorder.close(run_status="success")


def test_log_handler_captures_traceback_and_redacts_secrets(tmp_path: Path) -> None:
    run_dir = tmp_path / "logs-tb"
    secret = "super-secret-traceback-value"
    recorder = DiagnosticRecorder(run_dir, secret_values=[secret])
    try:
        logger = logging.getLogger("jung.test.diagnostics.tb")
        logger.setLevel(logging.ERROR)
        try:
            raise RuntimeError(f"boom with {secret}")
        except RuntimeError:
            logger.exception("failed in worker")
        payload = next(
            json.loads(line)
            for line in (run_dir / "trace.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if json.loads(line)["kind"] == "log.record"
        )
        assert payload["data"]["exception_type"] == "RuntimeError"
        assert secret not in payload["data"]["exception_message"]
        assert "traceback" in payload["data"]
        assert "test_log_handler_captures_traceback" in payload["data"]["traceback"]
        assert secret not in payload["data"]["traceback"]
        assert "[REDACTED]" in payload["data"]["traceback"]
    finally:
        recorder.close(run_status="success")


def test_diagnostic_log_handler_handles_formatting_failure(
    tmp_path: Path,
) -> None:
    class BrokenString:
        def __str__(self) -> str:
            raise RuntimeError("format failed")

    run_dir = tmp_path / "format-failure"
    recorder = DiagnosticRecorder(run_dir)
    try:
        assert recorder._log_handler is not None  # type: ignore[attr-defined]
        record = logging.LogRecord(
            name="jung.test.diagnostics.formatting",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="value=%s",
            args=(BrokenString(),),
            exc_info=None,
        )
        recorder._log_handler.emit(record)  # type: ignore[union-attr]

        with pytest.raises(DiagnosticCaptureError):
            recorder.close(run_status="success")
    finally:
        # If close() already raised, it may have removed the handler; ensure trace artifacts exist.
        if (run_dir / "manifest.json").exists():
            manifest = json.loads(
                (run_dir / "manifest.json").read_text(encoding="utf-8"),
            )
            assert manifest["evidence_complete"] is False
            errors = manifest.get("instrumentation_errors") or []
            assert any("diagnostic log capture failed" in str(err) for err in errors)


@pytest.mark.parametrize(
    ("raise_app_error", "mark_incomplete", "expect_capture_error"),
    [
        (False, False, False),
        (False, True, True),
        (True, False, False),
        (True, True, False),
    ],
)
def test_diagnostic_run_finalization_matrix(
    tmp_path: Path,
    raise_app_error: bool,
    mark_incomplete: bool,
    expect_capture_error: bool,
) -> None:
    run_dir = tmp_path / f"final-{raise_app_error}-{mark_incomplete}"

    def exercise() -> None:
        with DiagnosticRun(run_dir) as recorder:
            recorder.record("probe", {"ok": True})
            if mark_incomplete:
                recorder.capture_error("injected", "boom")
            if raise_app_error:
                raise RuntimeError("app failed")

    if raise_app_error:
        with pytest.raises(RuntimeError, match="app failed"):
            exercise()
    elif expect_capture_error:
        with pytest.raises(DiagnosticCaptureError, match="incomplete"):
            exercise()
    else:
        exercise()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_status"] == ("failed" if raise_app_error else "success")
    assert manifest["evidence_complete"] is (not mark_incomplete)


def test_capture_error_handles_exception_with_broken_str(
    tmp_path: Path,
) -> None:
    class BrokenMessageError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("broken exception message")

    run_dir = tmp_path / "broken-exception-message"

    with pytest.raises(DiagnosticCaptureError):
        with DiagnosticRun(run_dir) as recorder:
            recorder.capture_error(
                "instrumentation failed",
                BrokenMessageError(),
            )

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["evidence_complete"] is False
    assert any(
        "<exception message unavailable>" in message
        for message in manifest["instrumentation_errors"]
    )


@pytest.mark.asyncio
async def test_application_context_without_debug_run_dir_has_no_recorder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", ClosingFakeLLM)
    settings = ApplicationSettings(
        database_path=tmp_path / "no-debug.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        debug_run_dir=None,
    )
    async with application_context(settings) as runtime:
        assert runtime.recorder is None
