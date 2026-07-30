"""Local diagnostic evidence capture for explicit debug runs.

Sensitive prompts, responses, and related artifacts are written only when a
``DiagnosticRun`` is constructed for ``JUNG_DEBUG_RUN_DIR``. Ordinary console
logging remains separate.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import platform
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
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
_RESERVED_ARTIFACTS: Final = frozenset({"manifest.json", "trace.jsonl"})
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
_MIN_SECRET_LEN: Final = 8
_MAX_INSTRUMENTATION_ERRORS: Final = 64


@dataclass(frozen=True, slots=True)
class DiagnosticContext:
    request_id: str | None = None
    connection_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    client_message_id: str | None = None
    operation_id: str | None = None
    task_name: str | None = None
    llm_call_id: str | None = None
    store_call_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        return {
            key: value
            for key, value in (
                ("request_id", self.request_id),
                ("connection_id", self.connection_id),
                ("session_id", self.session_id),
                ("turn_id", self.turn_id),
                ("client_message_id", self.client_message_id),
                ("operation_id", self.operation_id),
                ("task_name", self.task_name),
                ("llm_call_id", self.llm_call_id),
                ("store_call_id", self.store_call_id),
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
    scope. Always resets via ContextVar tokens.
    """
    current = current_diagnostic_context()
    updates: dict[str, Any] = {}
    for name in DiagnosticContext.__dataclass_fields__:
        if name not in fields:
            continue
        value = fields[name]
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


class DiagnosticCaptureError(RuntimeError):
    """Raised when diagnostic evidence is incomplete without a primary error."""


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
    # bool is a subclass of int; treat it as non-numeric for credential safety.
    return value is None or (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    )


def _sanitize_mapping_item(
    key_str: str,
    item: Any,
    *,
    convert: Callable[[Any], Any],
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
    secrets = tuple(
        secret
        for secret in secret_values
        if isinstance(secret, str) and len(secret) >= _MIN_SECRET_LEN
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


class _DiagnosticLogHandler(logging.Handler):
    def __init__(self, recorder: DiagnosticRecorder) -> None:
        super().__init__()
        self._recorder = recorder
        self._reentering = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._reentering, "active", False):
            return
        if record.name == "jung.diagnostics" or record.name.startswith(
            "jung.diagnostics."
        ):
            return
        self._reentering.active = True
        try:
            extras = {
                key: value
                for key, value in record.__dict__.items()
                if key
                not in {
                    "name",
                    "msg",
                    "args",
                    "levelname",
                    "levelno",
                    "pathname",
                    "filename",
                    "module",
                    "exc_info",
                    "exc_text",
                    "stack_info",
                    "lineno",
                    "funcName",
                    "created",
                    "msecs",
                    "relativeCreated",
                    "thread",
                    "threadName",
                    "processName",
                    "process",
                    "message",
                    "taskName",
                }
                and not key.startswith("_")
            }
            data: dict[str, Any] = {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if extras:
                data["extra"] = extras
            if record.exc_info and record.exc_info[0] is not None:
                data["exception_type"] = record.exc_info[0].__name__
                data["exception_message"] = str(record.exc_info[1])
                formatter = logging.Formatter()
                data["traceback"] = formatter.formatException(record.exc_info)
            self._recorder.record("log.record", data)
        except Exception as exc:
            self._recorder.capture_error("diagnostic log capture failed", exc)
        finally:
            self._reentering.active = False


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
        self._metadata = dict(metadata or {})
        self._secret_values = tuple(
            value
            for value in secret_values
            if isinstance(value, str) and len(value) >= _MIN_SECRET_LEN
        )
        self._lock = threading.Lock()
        self._sequence = 0
        self._id_counters: dict[str, int] = {}
        self._started_monotonic = time.perf_counter()
        self._started_at = datetime.now(UTC)
        self._evidence_complete = True
        self._run_failed = False
        self._instrumentation_errors: list[str] = []
        self._error_counts: dict[str, int] = {}
        self._trace_file: Any = None
        self._log_handler: _DiagnosticLogHandler | None = None
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

        self._write_manifest(
            run_status="running",
            evidence_complete=True,
            finished_at=None,
        )
        self._install_log_handler()

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def evidence_complete(self) -> bool:
        return self._evidence_complete

    @property
    def instrumentation_errors(self) -> tuple[str, ...]:
        return tuple(self._instrumentation_errors)

    def artifact_path(self, name: str) -> Path:
        if not name or name in _RESERVED_ARTIFACTS:
            raise ValueError(f"invalid diagnostic artifact name: {name!r}")
        if "/" in name or "\\" in name or name in {".", ".."} or ".." in name:
            raise ValueError(f"invalid diagnostic artifact name: {name!r}")
        if Path(name).name != name:
            raise ValueError(f"invalid diagnostic artifact name: {name!r}")
        return self._run_dir / name

    def next_id(self, prefix: str) -> str:
        with self._lock:
            count = self._id_counters.get(prefix, 0) + 1
            self._id_counters[prefix] = count
            return f"{prefix}-{count}"

    def mark_run_failed(self) -> None:
        with self._lock:
            self._run_failed = True

    def capture_error(self, label: str, exc: BaseException | str) -> None:
        if isinstance(exc, BaseException):
            message = f"{label}: {type(exc).__name__}: {_safe_exception_message(exc)}"
        else:
            message = f"{label}: {exc}"
        message = str(sanitize_value(message, secret_values=self._secret_values))
        with self._lock:
            self._evidence_complete = False
            self._append_instrumentation_error_locked(message)

    def record(self, kind: str, data: Mapping[str, Any] | None = None) -> None:
        """Record an event without propagating instrumentation failures."""
        if self._closed:
            return
        try:
            payload = sanitize_value(
                dict(data or {}),
                secret_values=self._secret_values,
            )
            context = current_diagnostic_context().as_dict()
            now = datetime.now(UTC)
            # Build envelope without holding lock during serialization of user data
            # (already sanitized). Sequence assignment needs the lock.
            with self._lock:
                if self._closed or self._trace_file is None:
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
                except OSError as exc:
                    self._evidence_complete = False
                    self._append_instrumentation_error_locked(
                        f"trace write failed: {type(exc).__name__}"
                    )
        except Exception as exc:
            self.capture_error("record failed", exc)

    def close(
        self,
        *,
        run_status: str,
        primary_exception: BaseException | None = None,
    ) -> None:
        """Finalize artifacts; raise if incomplete with no primary error."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            evidence_complete = self._evidence_complete
            errors = list(self._instrumentation_errors)
            finished_at = datetime.now(UTC)

        self._remove_log_handler()
        try:
            if self._trace_file is not None:
                self._trace_file.flush()
                self._trace_file.close()
        except OSError as exc:
            evidence_complete = False
            errors.append(f"trace close failed: {type(exc).__name__}")
        finally:
            self._trace_file = None

        try:
            self._write_manifest(
                run_status=run_status,
                evidence_complete=evidence_complete,
                finished_at=finished_at,
                instrumentation_errors=errors,
            )
        except OSError as exc:
            evidence_complete = False
            sys.stderr.write(
                f"jung diagnostics: failed to write final manifest: "
                f"{type(exc).__name__}: {exc}\n"
            )
            if primary_exception is None:
                raise DiagnosticCaptureError(
                    "diagnostic evidence incomplete: final manifest write failed"
                ) from exc

        if not evidence_complete and primary_exception is None:
            raise DiagnosticCaptureError(
                "diagnostic evidence incomplete: "
                + ("; ".join(errors) if errors else "unknown instrumentation failure")
            )

    def _append_instrumentation_error_locked(self, message: str) -> None:
        count = self._error_counts.get(message, 0) + 1
        self._error_counts[message] = count
        if count == 1:
            if len(self._instrumentation_errors) < _MAX_INSTRUMENTATION_ERRORS:
                self._instrumentation_errors.append(message)
        elif (
            count == 2
            and len(self._instrumentation_errors) < _MAX_INSTRUMENTATION_ERRORS
        ):
            self._instrumentation_errors.append(f"{message} (repeated)")
        # Further repeats only bump the counter; message list stays capped.

    def _write_manifest(
        self,
        *,
        run_status: str,
        evidence_complete: bool,
        finished_at: datetime | None,
        instrumentation_errors: Sequence[str] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_status": run_status,
            "run_status_scope": "runtime_lifecycle",
            "evidence_complete": evidence_complete,
            "contains_sensitive_data": True,
            "started_at": self._started_at.isoformat(),
            "instrumentation_errors": list(
                instrumentation_errors
                if instrumentation_errors is not None
                else self._instrumentation_errors
            ),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        }
        if finished_at is not None:
            payload["finished_at"] = finished_at.isoformat()
        for key, value in self._metadata.items():
            if key in payload:
                continue
            payload[key] = sanitize_value(value, secret_values=self._secret_values)

        path = self._run_dir / "manifest.json"
        tmp = self._run_dir / "manifest.json.tmp"
        text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _install_log_handler(self) -> None:
        handler = _DiagnosticLogHandler(self)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger("jung")
        root.addHandler(handler)
        self._log_handler = handler

    def _remove_log_handler(self) -> None:
        handler = self._log_handler
        self._log_handler = None
        if handler is None:
            return
        logging.getLogger("jung").removeHandler(handler)
        handler.close()


class DiagnosticRun:
    """Owns recorder lifetime. Only this object may finalize the run."""

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
        run_failed = recorder._run_failed or exc_type is not None
        run_status = "failed" if run_failed else "success"
        try:
            recorder.close(run_status=run_status, primary_exception=exc)
        except DiagnosticCaptureError:
            if exc is not None:
                return False
            raise
        except Exception as finalize_exc:
            if exc is not None:
                sys.stderr.write(
                    f"jung diagnostics: finalize failed during primary error: "
                    f"{type(finalize_exc).__name__}: {finalize_exc}\n"
                )
                return False
            raise DiagnosticCaptureError(
                f"diagnostic finalize failed: {type(finalize_exc).__name__}"
            ) from finalize_exc
        return False
