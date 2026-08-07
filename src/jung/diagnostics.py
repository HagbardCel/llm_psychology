"""Lean local diagnostic logging for explicit debug runs.

Sensitive prompts, responses, and related artifacts are written only when a
``DiagnosticRun`` is constructed for ``JUNG_DEBUG_RUN_DIR``. Ordinary console
logging remains separate. Capture is best-effort after successful startup:
individual write failures never change application outcome.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel

SCHEMA_VERSION: Final = 1
_TOKEN_METRIC_KEYS: Final = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "max_completion_tokens",
        "total_tokens",
    }
)
_COLLAPSED_TOKEN_METRIC_KEYS: Final = frozenset(
    key.replace("_", "") for key in _TOKEN_METRIC_KEYS
)
_SENSITIVE_EXACT_KEYS: Final = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "password",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "auth_token",
    }
)
_SENSITIVE_COLLAPSED_EXACT_KEYS: Final = frozenset(
    key.replace("_", "") for key in _SENSITIVE_EXACT_KEYS
)


@dataclass(frozen=True, slots=True)
class DiagnosticContext:
    request_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    client_message_id: str | None = None
    operation_id: str | None = None
    task: str | None = None
    llm_call_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        return {
            key: value
            for key, value in (
                ("request_id", self.request_id),
                ("session_id", self.session_id),
                ("turn_id", self.turn_id),
                ("client_message_id", self.client_message_id),
                ("operation_id", self.operation_id),
                ("task", self.task),
                ("llm_call_id", self.llm_call_id),
            )
            if value is not None
        }


_diagnostic_context: ContextVar[DiagnosticContext | None] = ContextVar(
    "jung_diagnostic_context",
    default=None,
)


@contextmanager
def diagnostic_context(**fields: Any) -> Iterator[DiagnosticContext]:
    """Merge correlation fields for the current scope.

    Omitted fields inherit. Explicit ``None`` clears a field for the nested
    scope. Unknown fields raise ``TypeError``. Always resets via ContextVar tokens.
    """
    unknown = set(fields) - set(DiagnosticContext.__dataclass_fields__)
    if unknown:
        raise TypeError(f"unknown diagnostic context fields: {sorted(unknown)}")
    current = current_diagnostic_context()
    updates: dict[str, Any] = {}
    for name, value in fields.items():
        updates[name] = None if value is None else str(value)
    merged = replace(current, **updates) if updates else current
    token = _diagnostic_context.set(merged)
    try:
        yield merged
    finally:
        _diagnostic_context.reset(token)


def current_diagnostic_context() -> DiagnosticContext:
    current = _diagnostic_context.get()
    if current is None:
        return DiagnosticContext()
    return current


def sanitize_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        hostname = parts.hostname or ""
        port = parts.port
    except ValueError:
        return "[REDACTED_URL]"
    netloc = hostname
    if port:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _safe_exception_message(exc: BaseException) -> str:
    try:
        return str(exc)
    except Exception:
        return "<exception message unavailable>"


def _is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.casefold().replace("-", "_")
    collapsed = normalized.replace("_", "")
    if normalized in _TOKEN_METRIC_KEYS or collapsed in _COLLAPSED_TOKEN_METRIC_KEYS:
        return False
    if (
        normalized in _SENSITIVE_EXACT_KEYS
        or collapsed in _SENSITIVE_COLLAPSED_EXACT_KEYS
    ):
        return True
    if normalized.endswith(("_password", "_secret", "_api_key", "_token", "_tokens")):
        return True
    if collapsed.endswith(("password", "secret", "apikey", "token", "tokens")):
        return True
    return False


def _is_token_metric_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    collapsed = normalized.replace("_", "")
    return normalized in _TOKEN_METRIC_KEYS or collapsed in _COLLAPSED_TOKEN_METRIC_KEYS


def _is_token_metric_value(value: object) -> bool:
    return value is None or (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    )


def _sanitize_mapping_item(
    key_str: str,
    item: Any,
    *,
    convert: Any,
) -> Any:
    if _is_token_metric_key(key_str):
        if _is_token_metric_value(item):
            return item
        return "[REDACTED]"
    if _is_sensitive_key(key_str):
        return "[REDACTED]"
    return convert(item)


def sanitize_value(
    value: Any,
    *,
    secret_values: Sequence[str] = (),
) -> Any:
    """JSON-safe serialization with structural and exact-value redaction."""
    # Caller-designated secrets are always redacted, including short values.
    secrets = tuple(
        secret for secret in secret_values if isinstance(secret, str) and secret
    )

    def redact_string(text: str) -> str:
        result = text
        for secret in secrets:
            if secret and secret in result:
                result = result.replace(secret, "[REDACTED]")
        return result

    def convert(obj: Any, *, depth: int = 0) -> Any:
        if depth > 32:
            return "<max-depth>"
        if obj is None or isinstance(obj, (bool, int, float)):
            return obj
        if isinstance(obj, str):
            return redact_string(obj)
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            if isinstance(obj, datetime) and obj.tzinfo is None:
                return obj.replace(tzinfo=UTC).isoformat()
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, BaseModel):
            return convert(obj.model_dump(mode="json"), depth=depth + 1)
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return convert(dataclasses.asdict(obj), depth=depth + 1)
        if isinstance(obj, Mapping):
            return {
                str(key): _sanitize_mapping_item(
                    str(key),
                    item,
                    convert=lambda nested: convert(nested, depth=depth + 1),
                )
                for key, item in obj.items()
            }
        if isinstance(obj, (list, tuple, set, frozenset)):
            return [convert(item, depth=depth + 1) for item in obj]
        if isinstance(obj, bytes):
            return f"<bytes:{len(obj)}>"
        return redact_string(repr(obj))

    return convert(value)


class DiagnosticRecorder:
    """Append-only JSONL timeline writer for one diagnostic run."""

    def __init__(
        self,
        run_dir: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        secret_values: Sequence[str] = (),
    ) -> None:
        self._run_dir = Path(run_dir)
        self._secret_values = tuple(
            value for value in secret_values if isinstance(value, str) and value
        )
        self._lock = threading.Lock()
        self._sequence = 0
        self._id_counters: dict[str, int] = {}
        self._started_monotonic = time.perf_counter()
        self._run_failed = False
        self._write_failed = False
        self._warned_write_failure = False
        self._trace_file: Any = None
        self._closed = False

        self._run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
        try:
            os.chmod(self._run_dir, 0o700)
        except OSError:
            pass

        trace_path = self._run_dir / "trace.jsonl"
        self._trace_file = open(trace_path, "a", encoding="utf-8", buffering=1)
        try:
            os.chmod(trace_path, 0o600)
        except OSError:
            pass

        start_data: dict[str, Any] = {}
        if metadata:
            start_data.update(dict(metadata))
        self._write_line_or_raise("diagnostics.start", start_data)

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def run_failed(self) -> bool:
        return self._run_failed

    def next_id(self, prefix: str) -> str:
        with self._lock:
            count = self._id_counters.get(prefix, 0) + 1
            self._id_counters[prefix] = count
            return f"{prefix}-{count}"

    def mark_run_failed(self) -> None:
        with self._lock:
            self._run_failed = True

    def record(self, kind: str, data: Mapping[str, Any] | None = None) -> None:
        """Record an event without propagating write failures."""
        if self._closed or self._write_failed:
            return
        try:
            self._write_line(kind, dict(data or {}), raise_on_error=False)
        except Exception:
            self._latch_write_failure("record failed")

    def close(self, *, primary_exception: BaseException | None = None) -> None:
        """Emit diagnostics.end and close the trace. Never raises."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            run_failed = self._run_failed or primary_exception is not None

        status = "failed" if run_failed else "success"
        end_data: dict[str, object] = {"status": status}
        if primary_exception is not None:
            end_data["error_type"] = type(primary_exception).__name__
            end_data["error_message"] = _safe_exception_message(primary_exception)

        # Temporarily allow the terminal write even after close flagged;
        # use the write path while the file is still open.
        try:
            if not self._write_failed and self._trace_file is not None:
                self._write_line("diagnostics.end", end_data, raise_on_error=False)
        except Exception:
            self._latch_write_failure("diagnostics.end failed")

        try:
            if self._trace_file is not None:
                self._trace_file.flush()
                self._trace_file.close()
        except OSError as exc:
            self._latch_write_failure(f"trace close failed: {type(exc).__name__}")
        finally:
            self._trace_file = None

    def _write_line_or_raise(self, kind: str, data: Mapping[str, Any]) -> None:
        self._write_line(kind, dict(data), raise_on_error=True)

    def _write_line(
        self,
        kind: str,
        data: dict[str, Any],
        *,
        raise_on_error: bool,
    ) -> None:
        payload = sanitize_value(data, secret_values=self._secret_values)
        context = current_diagnostic_context().as_dict()
        now = datetime.now(UTC)
        with self._lock:
            if self._trace_file is None:
                if raise_on_error:
                    raise RuntimeError("diagnostic trace file is not open")
                return
            if self._write_failed and not raise_on_error:
                return
            self._sequence += 1
            sequence = self._sequence
            elapsed_ms = (time.perf_counter() - self._started_monotonic) * 1000.0
            line = json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "sequence": sequence,
                    "timestamp": now.isoformat(),
                    "elapsed_ms": round(elapsed_ms, 3),
                    "kind": kind,
                    "context": context,
                    "data": payload,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                default=str,
            )
            try:
                self._trace_file.write(line + "\n")
                self._trace_file.flush()
            except OSError:
                if raise_on_error:
                    raise
                self._write_failed = True
                self._warn_write_failure_locked("trace write failed")

    def _latch_write_failure(self, reason: str) -> None:
        with self._lock:
            self._write_failed = True
            self._warn_write_failure_locked(reason)

    def _warn_write_failure_locked(self, reason: str) -> None:
        if self._warned_write_failure:
            return
        self._warned_write_failure = True
        sys.stderr.write(f"jung diagnostics: {reason}\n")


class DiagnosticRun:
    """Owns recorder lifetime for one opt-in debug run."""

    def __init__(
        self,
        run_dir: str | Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        secret_values: Sequence[str] = (),
    ) -> None:
        self._run_dir = Path(run_dir)
        self._metadata = metadata
        self._secret_values = secret_values
        self._recorder: DiagnosticRecorder | None = None

    def __enter__(self) -> DiagnosticRecorder:
        self._recorder = DiagnosticRecorder(
            self._run_dir,
            metadata=self._metadata,
            secret_values=self._secret_values,
        )
        return self._recorder

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> bool:
        recorder = self._recorder
        if recorder is None:
            return False
        try:
            recorder.close(primary_exception=exc)
        except Exception as finalize_exc:
            sys.stderr.write(
                f"jung diagnostics: finalize failed: "
                f"{type(finalize_exc).__name__}: {finalize_exc}\n"
            )
        return False
